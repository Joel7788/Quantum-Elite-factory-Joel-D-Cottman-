"""Predictive disposition: match a contracted property to liquid cash buyers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import Assignment, Buyer, Offer, Underwriting

CENTS = Decimal("0.01")

# Match score weights; they sum to 1.
WEIGHT_PRICE_FIT = Decimal("0.35")
WEIGHT_REPAIR_FIT = Decimal("0.25")
WEIGHT_SPEED = Decimal("0.20")
WEIGHT_TRACK_RECORD = Decimal("0.20")

FAST_CLOSE_DAYS = 14
SLOW_CLOSE_DAYS = 45
TRACK_RECORD_SATURATION = 25


@dataclass(frozen=True)
class BuyerMatch:
    buyer: Buyer
    score: Decimal
    resale_price: Decimal


class MatchingError(ValueError):
    """Raised when no buyer in the repository fits the deal."""


def _ratio(value: Decimal, best: Decimal, worst: Decimal) -> Decimal:
    """Normalise ``value`` to 0-1 where ``best`` maps to 1 and ``worst`` to 0."""
    if best == worst:
        return Decimal("1")
    scaled = (value - worst) / (best - worst)
    return min(Decimal("1"), max(Decimal("0"), scaled))


def is_eligible(buyer: Buyer, market_key: str, resale_price: Decimal, repairs: Decimal) -> bool:
    """Hard buy-box gates: funds, market, price band, and rehab appetite."""
    return (
        buyer.proof_of_funds
        and buyer.covers_market(market_key)
        and buyer.min_price <= resale_price <= buyer.max_price
        and repairs <= buyer.max_repair_tolerance
    )


def score_buyer(buyer: Buyer, resale_price: Decimal, repairs: Decimal) -> Decimal:
    """Rank an eligible buyer: price headroom, rehab appetite, speed, history."""
    price_fit = _ratio(buyer.max_price, buyer.max_price, resale_price)
    repair_fit = _ratio(buyer.max_repair_tolerance, buyer.max_repair_tolerance, repairs)
    speed = _ratio(
        Decimal(buyer.close_days), Decimal(FAST_CLOSE_DAYS), Decimal(SLOW_CLOSE_DAYS)
    )
    track_record = _ratio(
        Decimal(min(buyer.deals_closed, TRACK_RECORD_SATURATION)),
        Decimal(TRACK_RECORD_SATURATION),
        Decimal("0"),
    )
    total = (
        WEIGHT_PRICE_FIT * price_fit
        + WEIGHT_REPAIR_FIT * repair_fit
        + WEIGHT_SPEED * speed
        + WEIGHT_TRACK_RECORD * track_record
    )
    return total.quantize(Decimal("0.0001"))


def rank_buyers(
    buyers: tuple[Buyer, ...],
    market_key: str,
    offer: Offer,
    underwriting: Underwriting,
) -> tuple[BuyerMatch, ...]:
    """Eligible buyers, best match first; ties broken by deals closed."""
    resale_price = (offer.amount + underwriting.assignment_fee).quantize(CENTS)
    matches = [
        BuyerMatch(
            buyer=buyer,
            score=score_buyer(buyer, resale_price, underwriting.repair_estimate),
            resale_price=resale_price,
        )
        for buyer in buyers
        if is_eligible(buyer, market_key, resale_price, underwriting.repair_estimate)
    ]
    return tuple(sorted(matches, key=lambda m: (m.score, m.buyer.deals_closed), reverse=True))


def assign_best_buyer(
    buyers: tuple[Buyer, ...],
    market_key: str,
    offer: Offer,
    underwriting: Underwriting,
) -> Assignment:
    ranked = rank_buyers(buyers, market_key, offer, underwriting)
    if not ranked:
        raise MatchingError(f"no eligible cash buyer for {market_key} at {offer.amount}")
    best = ranked[0]
    return Assignment(
        buyer=best.buyer,
        fee=underwriting.assignment_fee,
        match_score=best.score,
    )
