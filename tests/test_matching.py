from datetime import date
from decimal import Decimal

import pytest
from conftest import make_buyer

from quantum_elite import matching
from quantum_elite.models import Offer, Underwriting

MARKET = "norfolk|VA"
OFFER = Offer(
    lead_id="QE-TEST",
    amount=Decimal("100000"),
    earnest_money=Decimal("1000"),
    inspection_days=10,
    close_days=21,
    expires_on=date(2026, 8, 16),
)
UNDERWRITING = Underwriting(
    arv=Decimal("240000"),
    repair_estimate=Decimal("60000"),
    max_allowable_offer=Decimal("110000"),
    assignment_fee=Decimal("10000"),
    confidence=Decimal("0.9"),
)


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"proof_of_funds": False}, "no proof of funds"),
        ({"markets": ("richmond|VA",)}, "wrong market"),
        ({"max_price": "90000"}, "below price band"),
        ({"min_price": "200000", "max_price": "400000"}, "above price band"),
        ({"max_repair_tolerance": "10000"}, "rehab too heavy"),
    ],
)
def test_hard_gates_exclude_buyers(kwargs, reason):
    buyer = make_buyer(**kwargs)
    assert not matching.is_eligible(
        buyer, MARKET, Decimal("110000"), UNDERWRITING.repair_estimate
    ), reason


def test_eligible_buyer_passes_all_gates():
    assert matching.is_eligible(
        make_buyer(), MARKET, Decimal("110000"), UNDERWRITING.repair_estimate
    )


def test_score_is_bounded_and_rewards_headroom_speed_and_history():
    strong = matching.score_buyer(
        make_buyer(max_price="400000", max_repair_tolerance="200000", close_days=14,
                   deals_closed=40),
        Decimal("110000"),
        Decimal("60000"),
    )
    weak = matching.score_buyer(
        make_buyer(max_price="115000", max_repair_tolerance="61000", close_days=45,
                   deals_closed=0),
        Decimal("110000"),
        Decimal("60000"),
    )
    assert strong == Decimal("1.0000")
    assert Decimal("0") <= weak < strong


def test_rank_buyers_orders_best_first_and_drops_ineligible():
    best = make_buyer(buyer_id="CB-BEST", name="Best", deals_closed=40)
    slower = make_buyer(buyer_id="CB-SLOW", name="Slow", close_days=45, deals_closed=1)
    ineligible = make_buyer(buyer_id="CB-NOPOF", name="NoPOF", proof_of_funds=False)
    ranked = matching.rank_buyers((slower, ineligible, best), MARKET, OFFER, UNDERWRITING)
    assert [m.buyer.buyer_id for m in ranked] == ["CB-BEST", "CB-SLOW"]
    assert ranked[0].resale_price == Decimal("110000.00")


def test_ties_are_broken_by_deals_closed():
    a = make_buyer(buyer_id="CB-A", deals_closed=25)
    b = make_buyer(buyer_id="CB-B", deals_closed=30)
    ranked = matching.rank_buyers((a, b), MARKET, OFFER, UNDERWRITING)
    assert [m.score for m in ranked] == [ranked[0].score, ranked[0].score]
    assert ranked[0].buyer.buyer_id == "CB-B"


def test_assign_best_buyer_returns_assignment_with_fee():
    assignment = matching.assign_best_buyer((make_buyer(),), MARKET, OFFER, UNDERWRITING)
    assert assignment.buyer.buyer_id == "CB-TEST"
    assert assignment.fee == UNDERWRITING.assignment_fee
    assert assignment.match_score > Decimal("0")


def test_assign_best_buyer_raises_when_no_buyer_fits():
    with pytest.raises(matching.MatchingError, match="no eligible cash buyer"):
        matching.assign_best_buyer(
            (make_buyer(markets=("austin|TX",)),), MARKET, OFFER, UNDERWRITING
        )


def test_zero_headroom_scores_a_perfect_fit_without_dividing_by_zero():
    # max_price == resale_price collapses the normalisation range to a point.
    exact = make_buyer(buyer_id="CB-EXACT", max_price="110000")
    ranked = matching.rank_buyers((exact,), MARKET, OFFER, UNDERWRITING)
    assert len(ranked) == 1
    assert ranked[0].resale_price == Decimal("110000.00")
    assert ranked[0].score == matching.score_buyer(
        exact, Decimal("110000.00"), UNDERWRITING.repair_estimate
    )
