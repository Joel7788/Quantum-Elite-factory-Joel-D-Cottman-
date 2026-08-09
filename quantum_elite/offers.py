"""Offer generation for the acquisition side."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .models import Lead, Offer, Underwriting

CENTS = Decimal("0.01")

DEFAULT_INSPECTION_DAYS = 10
DEFAULT_CLOSE_DAYS = 21
OFFER_VALID_DAYS = 7
EARNEST_MONEY_RATIO = Decimal("0.01")
MIN_EARNEST_MONEY = Decimal("500")

# Highly motivated sellers trade price for speed, so lead with a lower opener.
ANCHOR_DISCOUNTS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.65"), Decimal("0.88")),
    (Decimal("0.35"), Decimal("0.94")),
)


class OfferError(ValueError):
    """Raised when no viable offer can be generated."""


def anchor_ratio(motivation_score: Decimal) -> Decimal:
    """Fraction of MAO to open at, given seller motivation."""
    for threshold, ratio in ANCHOR_DISCOUNTS:
        if motivation_score >= threshold:
            return ratio
    return Decimal("1.00")


def earnest_money(amount: Decimal) -> Decimal:
    return max(MIN_EARNEST_MONEY, (amount * EARNEST_MONEY_RATIO).quantize(CENTS))


def generate_offer(
    lead: Lead,
    underwriting: Underwriting,
    motivation_score: Decimal,
    as_of: date | None = None,
) -> Offer:
    """Open below MAO when motivation is high, never above MAO or the ask."""
    if not underwriting.is_viable:
        raise OfferError(f"lead {lead.lead_id} has no viable spread; not offering")

    as_of = as_of or date.today()
    amount = (underwriting.max_allowable_offer * anchor_ratio(motivation_score)).quantize(CENTS)
    if lead.asking_price is not None:
        amount = min(amount, lead.asking_price.quantize(CENTS))

    return Offer(
        lead_id=lead.lead_id,
        amount=amount,
        earnest_money=earnest_money(amount),
        inspection_days=DEFAULT_INSPECTION_DAYS,
        close_days=DEFAULT_CLOSE_DAYS,
        expires_on=as_of + timedelta(days=OFFER_VALID_DAYS),
    )
