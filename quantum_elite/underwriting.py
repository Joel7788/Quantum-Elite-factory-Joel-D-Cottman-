"""Underwriting engine: ARV, repair estimate, and maximum allowable offer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median

from .models import Comparable, PropertyCondition, PropertyData, Underwriting

CENTS = Decimal("0.01")

# Per-square-foot rehab budgets by condition band.
REPAIR_COST_PER_SQFT: dict[PropertyCondition, Decimal] = {
    PropertyCondition.TURNKEY: Decimal("2"),
    PropertyCondition.COSMETIC: Decimal("18"),
    PropertyCondition.MODERATE: Decimal("38"),
    PropertyCondition.HEAVY: Decimal("65"),
    PropertyCondition.TEARDOWN: Decimal("95"),
}

# Extra rehab budget for aging systems (roof, electrical, plumbing, HVAC).
AGE_SURCHARGE_PER_SQFT = Decimal("6")
AGE_SURCHARGE_YEARS = 50

# Comparable-sale eligibility bounds.
MAX_COMP_AGE_DAYS = 365
MAX_COMP_DISTANCE_MILES = Decimal("1.5")
MIN_COMPS_FOR_CONFIDENCE = 3

# Classic 70% rule: investor buys at 70% of ARV minus rehab.
ARV_PURCHASE_RATIO = Decimal("0.70")
DEFAULT_ASSIGNMENT_FEE = Decimal("10000")
MIN_ASSIGNMENT_FEE = Decimal("2500")


class UnderwritingError(ValueError):
    """Raised when a property cannot be underwritten from available data."""


@dataclass(frozen=True)
class ArvEstimate:
    value: Decimal
    comps_used: int
    price_per_sqft: Decimal
    fell_back_to_assessed: bool

    @property
    def confidence(self) -> Decimal:
        """Confidence rises with comp count and collapses on assessed-value fallback."""
        if self.fell_back_to_assessed:
            return Decimal("0.35")
        ratio = Decimal(min(self.comps_used, MIN_COMPS_FOR_CONFIDENCE)) / Decimal(
            MIN_COMPS_FOR_CONFIDENCE
        )
        return (Decimal("0.55") + Decimal("0.40") * ratio).quantize(Decimal("0.01"))


def eligible_comparables(
    property_data: PropertyData, as_of: date | None = None
) -> tuple[Comparable, ...]:
    """Comps within the distance and recency windows."""
    as_of = as_of or date.today()
    return tuple(
        comp
        for comp in property_data.comparables
        if comp.distance_miles <= MAX_COMP_DISTANCE_MILES
        and 0 <= (as_of - comp.sold_on).days <= MAX_COMP_AGE_DAYS
    )


def estimate_arv(property_data: PropertyData, as_of: date | None = None) -> ArvEstimate:
    """ARV from the median comp price-per-sqft, falling back to assessed value."""
    comps = eligible_comparables(property_data, as_of)
    if not comps:
        if property_data.assessed_value <= 0:
            raise UnderwritingError(
                f"no eligible comps and no assessed value for {property_data.address.one_line}"
            )
        return ArvEstimate(
            value=property_data.assessed_value.quantize(CENTS),
            comps_used=0,
            price_per_sqft=(
                property_data.assessed_value / Decimal(property_data.square_feet)
            ).quantize(CENTS),
            fell_back_to_assessed=True,
        )

    ppsf = median(comp.price_per_square_foot for comp in comps)
    return ArvEstimate(
        value=(ppsf * Decimal(property_data.square_feet)).quantize(CENTS),
        comps_used=len(comps),
        price_per_sqft=ppsf.quantize(CENTS),
        fell_back_to_assessed=False,
    )


def estimate_repairs(property_data: PropertyData, as_of: date | None = None) -> Decimal:
    """Rehab budget from condition band plus an aging-systems surcharge."""
    as_of = as_of or date.today()
    per_sqft = REPAIR_COST_PER_SQFT[property_data.condition]
    if as_of.year - property_data.year_built >= AGE_SURCHARGE_YEARS:
        per_sqft += AGE_SURCHARGE_PER_SQFT
    return (per_sqft * Decimal(property_data.square_feet)).quantize(CENTS)


def maximum_allowable_offer(
    arv: Decimal, repair_estimate: Decimal, assignment_fee: Decimal
) -> Decimal:
    """MAO under the 70% rule, floored at zero rather than going negative."""
    mao = arv * ARV_PURCHASE_RATIO - repair_estimate - assignment_fee
    return max(Decimal("0"), mao).quantize(CENTS)


def underwrite(
    property_data: PropertyData,
    assignment_fee: Decimal = DEFAULT_ASSIGNMENT_FEE,
    as_of: date | None = None,
) -> Underwriting:
    """Full underwrite; the assignment fee is trimmed before the MAO hits zero."""
    if assignment_fee < MIN_ASSIGNMENT_FEE:
        raise UnderwritingError(
            f"assignment fee {assignment_fee} is below the {MIN_ASSIGNMENT_FEE} floor"
        )
    arv = estimate_arv(property_data, as_of)
    repairs = estimate_repairs(property_data, as_of)

    fee = assignment_fee
    mao = maximum_allowable_offer(arv.value, repairs, fee)
    if mao == 0:
        # Preserve a viable offer by shrinking the fee to the available headroom.
        headroom = arv.value * ARV_PURCHASE_RATIO - repairs
        fee = max(MIN_ASSIGNMENT_FEE, min(assignment_fee, headroom / Decimal("2")))
        fee = fee.quantize(CENTS)
        mao = maximum_allowable_offer(arv.value, repairs, fee)

    return Underwriting(
        arv=arv.value,
        repair_estimate=repairs,
        max_allowable_offer=mao,
        assignment_fee=fee,
        confidence=arv.confidence,
    )
