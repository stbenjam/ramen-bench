"""Price ATIF trajectories at pinned published list rates."""

from __future__ import annotations

from decimal import Decimal

OPENAI_SOURCE = "https://developers.openai.com/api/docs/pricing"
# USD per million tokens, keyed by "<Harbor provider>/<provider model ID>". A tiered
# model gives (short, long) context rates and the prompt size above which a request
# is long; a flat model gives one rate per category and is priced from run totals.
RATES = {
    "openai/gpt-6.2-sol": {
        "source": OPENAI_SOURCE,
        "asOf": "2026-11-17",
        "tier": "Standard",
        "longContextAbove": 272_000,
        "input": ("2", "4"),
        "cachedInput": ("0.10", "0.20"),
        "output": ("10", "15"),
    },
    "openai/gpt-6.2-astra": {
        "source": OPENAI_SOURCE,
        "asOf": "2026-11-17",
        "tier": "Standard",
        "longContextAbove": 272_000,
        "input": ("8", "16"),
        "cachedInput": ("0.40", "0.80"),
        "output": ("40", "60"),
    },
    "openrouter/google/gemini-4-neon": {
        "source": "https://openrouter.ai/google/gemini-4-neon",
        "asOf": "2026-11-18",
        "tier": "OpenRouter",
        "input": "3",
        "cachedInput": "0.15",
        "output": "15",
    },
}
# Google publishes no API rate for Neon, so native Antigravity runs use OpenRouter's.
RATES["gemini/gemini-4-neon"] = RATES["openrouter/google/gemini-4-neon"]
CATEGORIES = ("input", "cachedInput", "output")
MILLION = Decimal(1_000_000)


def requests(trajectory: dict, tiered: bool) -> list[dict] | None:
    """Per-request metrics for tiered rates; run totals suffice for flat rates."""
    steps = [
        step["metrics"] for step in trajectory.get("steps", []) if step.get("metrics")
    ]
    if tiered:
        return steps or None
    final = trajectory["final_metrics"]
    return [
        {
            "prompt_tokens": final["total_prompt_tokens"],
            "cached_tokens": final.get("total_cached_tokens") or 0,
            "completion_tokens": final["total_completion_tokens"],
            "extra": {
                "cache_write_input_tokens": (final.get("extra") or {}).get(
                    "total_cache_write_input_tokens"
                )
            },
        }
    ]


def list_cost(model: str, trajectory: dict) -> tuple[dict, dict] | None:
    """Return (cost, evidence), or None when the model or a token category is unpriced.

    ATIF prompt tokens include cached input, and completion tokens include reasoning.
    Cache writes are left unpriced because their recorded duration tier is unknown.
    """
    rates = RATES.get(model)
    if rates is None:
        return None
    tiered = "longContextAbove" in rates
    metrics = requests(trajectory, tiered)
    if metrics is None:
        return None
    amounts = dict.fromkeys(CATEGORIES, Decimal(0))
    long_requests = 0
    for request in metrics:
        if (request.get("extra") or {}).get("cache_write_input_tokens"):
            return None
        prompt = request["prompt_tokens"]
        cached = request.get("cached_tokens") or 0
        tier = int(tiered and prompt > rates["longContextAbove"])
        long_requests += tier
        counts = {
            "input": prompt - cached,
            "cachedInput": cached,
            "output": request["completion_tokens"],
        }
        for key, count in counts.items():
            rate = rates[key][tier] if tiered else rates[key]
            amounts[key] += count * Decimal(rate) / MILLION
    cost = {
        "currency": "USD",
        **{key: float(value) for key, value in amounts.items()},
        "total": float(sum(amounts.values())),
        "estimated": True,
    }
    evidence = {
        "source": rates["source"],
        "asOf": rates["asOf"],
        "tier": rates["tier"],
        "usdPerMillionTokens": {
            key: dict(zip(("short", "long"), rates[key], strict=True))
            if tiered
            else rates[key]
            for key in CATEGORIES
        },
        "basis": "API-equivalent published list prices; not a recorded charge",
    }
    if tiered:
        evidence["longContextAbove"] = rates["longContextAbove"]
        evidence["longContextRequests"] = long_requests
    return cost, evidence
