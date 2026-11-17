"""Price ATIF trajectories at pinned published list rates, request by request."""

from __future__ import annotations

from decimal import Decimal

OPENAI_SOURCE = "https://developers.openai.com/api/docs/pricing"
OPENAI_AS_OF = "2026-11-17"
# Standard tier, USD per million tokens, as (short context, long context).
# Long-context rates apply to requests above the threshold of prompt tokens.
RATES = {
    "gpt-6.2-sol": {
        "source": OPENAI_SOURCE,
        "asOf": OPENAI_AS_OF,
        "longContextAbove": 272_000,
        "input": ("2", "4"),
        "cachedInput": ("0.10", "0.20"),
        "output": ("10", "15"),
    },
    "gpt-6.2-astra": {
        "source": OPENAI_SOURCE,
        "asOf": OPENAI_AS_OF,
        "longContextAbove": 272_000,
        "input": ("8", "16"),
        "cachedInput": ("0.40", "0.80"),
        "output": ("40", "60"),
    },
}


def list_cost(model: str, steps: list[dict]) -> tuple[dict, dict] | None:
    """Return (cost, evidence), or None when the model or a token category is unpriced.

    ATIF prompt tokens include cached input, and completion tokens include reasoning.
    Cache writes are left unpriced because their recorded duration tier is unknown.
    """
    rates = RATES.get(model)
    if rates is None:
        return None
    million = Decimal(1_000_000)
    amounts = {"input": Decimal(0), "cachedInput": Decimal(0), "output": Decimal(0)}
    long_requests = 0
    for step in steps:
        metrics = step.get("metrics")
        if not metrics:
            continue
        if (metrics.get("extra") or {}).get("cache_write_input_tokens"):
            return None
        prompt = metrics["prompt_tokens"]
        cached = metrics.get("cached_tokens") or 0
        tier = int(prompt > rates["longContextAbove"])
        long_requests += tier
        amounts["input"] += (prompt - cached) * Decimal(rates["input"][tier]) / million
        amounts["cachedInput"] += cached * Decimal(rates["cachedInput"][tier]) / million
        amounts["output"] += (
            metrics["completion_tokens"] * Decimal(rates["output"][tier]) / million
        )
    cost = {
        "currency": "USD",
        **{key: float(value) for key, value in amounts.items()},
        "total": float(sum(amounts.values())),
        "estimated": True,
    }
    evidence = {
        **{key: rates[key] for key in ("source", "asOf", "longContextAbove")},
        "usdPerMillionTokens": {
            key: dict(zip(("short", "long"), rates[key], strict=True))
            for key in ("input", "cachedInput", "output")
        },
        "tier": "Standard",
        "longContextRequests": long_requests,
        "basis": "API-equivalent published list prices; not a subscription charge",
    }
    return cost, evidence
