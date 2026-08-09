"""Neural_Smelter predictive motivation scoring.

The score is a transparent, auditable weighted model rather than an opaque one:
every lead's score can be explained signal-by-signal via ``explain``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import DistressSignal, Lead

ENGINE_VERSION = "Neural_Smelter_v9"

# Marginal contribution of each distress signal to the motivation score.
SIGNAL_WEIGHTS: dict[DistressSignal, Decimal] = {
    DistressSignal.PRE_FORECLOSURE: Decimal("0.30"),
    DistressSignal.TAX_DELINQUENT: Decimal("0.20"),
    DistressSignal.PROBATE: Decimal("0.18"),
    DistressSignal.DIVORCE: Decimal("0.14"),
    DistressSignal.CODE_VIOLATION: Decimal("0.12"),
    DistressSignal.VACANT: Decimal("0.16"),
    DistressSignal.ABSENTEE_OWNER: Decimal("0.10"),
    DistressSignal.TIRED_LANDLORD: Decimal("0.10"),
    DistressSignal.EXPIRED_LISTING: Decimal("0.08"),
}

# Days on market past which staleness stops adding motivation.
DOM_SATURATION_DAYS = 180
DOM_MAX_WEIGHT = Decimal("0.15")
REACHABLE_CONTACT_WEIGHT = Decimal("0.05")

HOT_THRESHOLD = Decimal("0.65")
WARM_THRESHOLD = Decimal("0.35")


@dataclass(frozen=True)
class ScoreComponent:
    label: str
    weight: Decimal


@dataclass(frozen=True)
class ScoreBreakdown:
    """An auditable explanation of a motivation score."""

    score: Decimal
    components: tuple[ScoreComponent, ...]
    engine_version: str = ENGINE_VERSION

    @property
    def band(self) -> str:
        if self.score >= HOT_THRESHOLD:
            return "hot"
        if self.score >= WARM_THRESHOLD:
            return "warm"
        return "cold"


def _clamp_unit(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value))


def days_on_market_weight(days_on_market: int | None) -> Decimal:
    """Staleness weight, ramping linearly to ``DOM_MAX_WEIGHT`` at saturation."""
    if not days_on_market or days_on_market <= 0:
        return Decimal("0")
    ratio = min(Decimal("1"), Decimal(days_on_market) / Decimal(DOM_SATURATION_DAYS))
    return (DOM_MAX_WEIGHT * ratio).quantize(Decimal("0.0001"))


def explain(lead: Lead) -> ScoreBreakdown:
    """Score a lead's motivation in the 0-1 range, with per-signal attribution."""
    components: list[ScoreComponent] = []
    for signal in dict.fromkeys(lead.distress_signals):
        components.append(ScoreComponent(signal.value, SIGNAL_WEIGHTS[signal]))

    dom_weight = days_on_market_weight(lead.days_on_market)
    if dom_weight > 0:
        components.append(ScoreComponent("days_on_market", dom_weight))

    if lead.best_contact is not None:
        components.append(
            ScoreComponent(
                "reachable_contact",
                (REACHABLE_CONTACT_WEIGHT * lead.best_contact.confidence).quantize(
                    Decimal("0.0001")
                ),
            )
        )

    total = sum((component.weight for component in components), Decimal("0"))
    return ScoreBreakdown(
        score=_clamp_unit(total).quantize(Decimal("0.0001")),
        components=tuple(components),
    )


def score_lead(lead: Lead) -> Decimal:
    return explain(lead).score
