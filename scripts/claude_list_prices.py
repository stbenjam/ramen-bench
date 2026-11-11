"""Price Claude Code accounting at pinned official list rates."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

SOURCE = "https://platform.claude.com/docs/en/models/sonnet-5-5/overview"
AS_OF = "2026-09-30"
RATES = {"input": 2, "output": 10, "cacheRead": 0.2, "cacheWrite5m": 2.5, "cacheWrite1h": 4}


def sonnet_list_cost(messages: list[dict], state: dict) -> tuple[dict, dict] | None:
    models = state.get("modelUsage", {})
    main = models.get("claude-sonnet-5-5")
    if not main:
        return None
    # Auxiliary Haiku accounting is already recorded by the harness. Do not
    # treat a globally unknown-model flag as proof of another model's price.
    other = Decimal(0)
    for model, usage in models.items():
        if model == "claude-sonnet-5-5":
            continue
        value = usage.get("costUSD")
        if model != "claude-haiku-4-5-20251001" or not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            return None
        other += Decimal(str(value))
    for key in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"):
        value = main.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
    if main.get("webSearchRequests", 0):
        return None
    five = hour = 0
    for row in messages:
        message = row.get("message", {})
        if message.get("model") != "claude-sonnet-5-5":
            continue
        usage = message.get("usage", {})
        split = usage.get("cache_creation")
        if not isinstance(split, dict):
            continue
        values = [split.get("ephemeral_5m_input_tokens"), split.get("ephemeral_1h_input_tokens")]
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in values):
            return None
        if sum(values) != usage.get("cache_creation_input_tokens"):
            raise ValueError("Recorded cache duration categories do not match cache writes")
        five += values[0]
        hour += values[1]
    unclassified = main["cacheCreationInputTokens"] - five - hour
    if unclassified < 0:
        raise ValueError("Recorded cache writes exceed cumulative harness accounting")
    # Some auxiliary/retried requests have cumulative usage but no public
    # response snapshot. Use the upper tariff bound for those cache writes,
    # disclose the range, and never invent a duration for the missing requests.
    million = Decimal(1_000_000)
    costs = {
        "input": Decimal(main["inputTokens"]) * Decimal(str(RATES["input"])) / million,
        "output": Decimal(main["outputTokens"]) * Decimal(str(RATES["output"])) / million,
        "cachedInput": Decimal(main["cacheReadInputTokens"]) * Decimal(str(RATES["cacheRead"])) / million,
        "cacheCreationInput": (Decimal(five) * Decimal(str(RATES["cacheWrite5m"])) + Decimal(hour + unclassified) * Decimal(str(RATES["cacheWrite1h"]))) / million,
        "other": other,
    }
    total = sum(costs.values())
    cache_range = Decimal(unclassified) * (Decimal(str(RATES["cacheWrite1h"])) - Decimal(str(RATES["cacheWrite5m"]))) / million
    cost = {"currency": "USD", **{k: float(v) for k, v in costs.items()}, "total": float(total), "estimated": True}
    evidence: dict[str, Any] = {
        "source": SOURCE, "asOf": AS_OF, "usdPerMillionTokens": RATES,
        "cacheWrite5mTokens": five, "cacheWrite1hTokens": hour,
        "cacheWriteUnclassifiedTokens": unclassified,
        "unclassifiedCacheWriteTreatment": "upper tariff bound; duration unknown",
        "totalRangeUsd": [float(total - cache_range), float(total)],
        "auxiliaryCostSource": "recorded Claude Code Haiku costUSD",
        "thinkingIncludedInOutput": True,
    }
    return cost, evidence


# Official list rates for models Claude Code can record without pricing.
LIST_PRICE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
LIST_PRICE_AS_OF = "2026-11-11"
LIST_RATES = {
    "claude-fable-5-2": {
        "input": 8,
        "output": 40,
        "cacheRead": 0.2,
        "cacheWrite5m": 10,
        "cacheWrite1h": 16,
    },
}
TOKEN_RATES = {
    "inputTokens": ("input", "input"),
    "outputTokens": ("output", "output"),
    "cacheReadInputTokens": ("cachedInput", "cacheRead"),
    "cacheCreationEphemeral5mInputTokens": ("cacheCreationInput", "cacheWrite5m"),
    "cacheCreationEphemeral1hInputTokens": ("cacheCreationInput", "cacheWrite1h"),
}


def model_usage_list_cost(
    model_usage: dict, usage: dict
) -> tuple[dict, dict] | None:
    """Price Claude Code modelUsage at pinned list rates, or None if any input is unknown."""
    # Fast mode and US-only inference carry multipliers; web searches are billed separately.
    if usage.get("speed") != "standard" or usage.get("inference_geo") != "global":
        return None
    million = Decimal(1_000_000)
    costs = dict.fromkeys(("input", "output", "cachedInput", "cacheCreationInput"), Decimal(0))
    for model, row in model_usage.items():
        rates = LIST_RATES.get(model)
        if rates is None or row.get("webSearchRequests", 0):
            return None
        counts = {key: row.get(key) for key in (*TOKEN_RATES, "cacheCreationInputTokens")}
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values()):
            return None
        written = counts["cacheCreationEphemeral5mInputTokens"] + counts["cacheCreationEphemeral1hInputTokens"]
        if written != counts["cacheCreationInputTokens"]:
            return None
        for key, (category, rate) in TOKEN_RATES.items():
            costs[category] += Decimal(counts[key]) * Decimal(str(rates[rate])) / million
    cost = {
        "currency": "USD",
        **{key: float(value) for key, value in costs.items()},
        "total": float(sum(costs.values())),
        "estimated": True,
    }
    evidence = {
        "source": LIST_PRICE_SOURCE,
        "asOf": LIST_PRICE_AS_OF,
        "usdPerMillionTokens": {model: LIST_RATES[model] for model in model_usage},
        "tokenSource": "Claude Code modelUsage, including recorded auxiliary requests",
        "thinkingIncludedInOutput": True,
    }
    return cost, evidence
