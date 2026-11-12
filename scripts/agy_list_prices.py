"""Pinned published list rates for recorded agy usage."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SOURCE = "https://ai.google.dev/gemini-api/docs/pricing#gemini-4-argon"
AS_OF = "2026-10-15"


def list_cost(usage: dict, rates: tuple[str, str, str]) -> dict:
    """Price each recorded category once; thinking is already inside output."""
    amounts = {}
    for field, category, rate in zip(
        ("input", "cachedInput", "output"),
        ("input_tokens", "cache_read_tokens", "output_tokens"),
        rates,
        strict=True,
    ):
        count = usage[category]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Invalid recorded agy token count")
        amounts[field] = Decimal(count) * Decimal(rate) / 1_000_000
    return {
        "currency": "USD",
        **{key: float(value) for key, value in amounts.items()},
        "cacheCreationInput": 0,
        "other": 0,
        "total": float(sum(amounts.values())),
        "estimated": True,
    }


def rate_fields(rates: tuple[str, str, str]) -> dict:
    return {
        "inputUsdPerMillion": float(rates[0]),
        "cachedInputUsdPerMillion": float(rates[1]),
        "outputUsdPerMillion": float(rates[2]),
        "outputIncludesThinking": True,
        "cacheType": "implicit",
    }


def argon_list_cost(usage: dict, completed_at: str) -> tuple[dict, dict]:
    """Price recorded categories once; callers retain unknown failed-request usage."""
    day = date.fromisoformat(completed_at[:10])
    if day < date(2026, 10, 15):
        raise ValueError("Argon run predates this pinned rate snapshot")
    introductory = day <= date(2026, 11, 30)
    rates = ("2", "0.10", "10") if introductory else ("4", "0.20", "20")
    provenance = {
        "source": SOURCE,
        "pinnedAt": AS_OF,
        "model": "gemini-4-argon",
        "tier": "Standard",
        "basis": "API-equivalent published list prices; not a subscription charge",
        "introductory": introductory,
        "effectiveThrough": "2026-11-30" if introductory else None,
        **rate_fields(rates),
    }
    return list_cost(usage, rates), provenance


@dataclass(frozen=True)
class OpenRouterRates:
    """OpenRouter's published per-million rates for one model, pinned on a date."""

    model: str
    pinned_at: str
    first_day: str
    last_day: str | None
    rates: tuple[str, str, str]
    basis: str
    introductory: bool

    @property
    def source(self) -> str:
        return f"https://openrouter.ai/{self.model}"

    def __call__(self, usage: dict, completed_at: str) -> tuple[dict, dict]:
        day = completed_at[:10]
        if day < self.first_day or (self.last_day and day > self.last_day):
            raise ValueError(
                f"{self.model} run falls outside this pinned rate snapshot"
            )
        provenance = {
            "source": self.source,
            "pinnedAt": self.pinned_at,
            "model": self.model,
            "tier": "OpenRouter",
            "basis": self.basis,
            "introductory": self.introductory,
            "effectiveThrough": None,
            **rate_fields(self.rates),
        }
        return list_cost(usage, self.rates), provenance


# The launch discount has no published end date, so only runs up to the pin.
CARBON = OpenRouterRates(
    "google/gemini-4-carbon",
    "2026-11-11",
    "2026-11-10",
    "2026-11-11",
    ("2", "0.10", "10"),
    "Published OpenRouter list prices with the 50% launch discount; not a recorded charge",
    True,
)
HYDROGEN = OpenRouterRates(
    "google/gemini-4-hydrogen",
    "2026-11-12",
    "2026-11-12",
    None,
    ("1.5", "0.075", "7.5"),
    "Published OpenRouter standard list prices; not a recorded charge",
    False,
)
