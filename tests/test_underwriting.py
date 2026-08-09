from datetime import date
from decimal import Decimal

import pytest
from conftest import AS_OF, make_address, make_comparable, make_property

from quantum_elite import underwriting as uw
from quantum_elite.models import PropertyCondition


def test_eligible_comparables_filters_distance_and_recency():
    close_recent = make_comparable(street="1 A St", distance_miles="1.0", sold_on=date(2026, 6, 1))
    too_far = make_comparable(street="2 A St", distance_miles="3.0")
    too_old = make_comparable(street="3 A St", sold_on=date(2024, 1, 1))
    in_future = make_comparable(street="4 A St", sold_on=date(2027, 1, 1))
    prop = make_property(comparables=(close_recent, too_far, too_old, in_future))
    assert uw.eligible_comparables(prop, AS_OF) == (close_recent,)


def test_eligible_comparables_defaults_to_today():
    prop = make_property(comparables=(make_comparable(sold_on=date.today()),))
    assert len(uw.eligible_comparables(prop)) == 1


def test_arv_uses_median_comp_price_per_sqft():
    comps = (
        make_comparable(street="1 A St", sold_price="160000", square_feet=1000),
        make_comparable(street="2 A St", sold_price="150000", square_feet=1000),
        make_comparable(street="3 A St", sold_price="140000", square_feet=1000),
    )
    estimate = uw.estimate_arv(make_property(square_feet=1200, comparables=comps), AS_OF)
    assert estimate.price_per_sqft == Decimal("150.00")
    assert estimate.value == Decimal("180000.00")
    assert estimate.comps_used == 3
    assert not estimate.fell_back_to_assessed
    assert estimate.confidence == Decimal("0.95")


def test_arv_confidence_scales_with_comp_count():
    one_comp = make_property(comparables=(make_comparable(),))
    assert uw.estimate_arv(one_comp, AS_OF).confidence == Decimal("0.68")


def test_arv_falls_back_to_assessed_value_without_comps():
    prop = make_property(square_feet=1000, assessed_value="200000", comparables=())
    estimate = uw.estimate_arv(prop, AS_OF)
    assert estimate.fell_back_to_assessed
    assert estimate.value == Decimal("200000.00")
    assert estimate.price_per_sqft == Decimal("200.00")
    assert estimate.confidence == Decimal("0.35")


def test_arv_raises_without_comps_or_assessed_value():
    prop = make_property(assessed_value="0", comparables=())
    with pytest.raises(uw.UnderwritingError, match="no eligible comps"):
        uw.estimate_arv(prop, AS_OF)


@pytest.mark.parametrize(
    "condition, expected",
    [
        (PropertyCondition.TURNKEY, "2000.00"),
        (PropertyCondition.COSMETIC, "18000.00"),
        (PropertyCondition.MODERATE, "38000.00"),
        (PropertyCondition.HEAVY, "65000.00"),
        (PropertyCondition.TEARDOWN, "95000.00"),
    ],
)
def test_repair_estimate_by_condition(condition, expected):
    prop = make_property(condition=condition, square_feet=1000, year_built=2005)
    assert uw.estimate_repairs(prop, AS_OF) == Decimal(expected)


def test_repair_estimate_adds_age_surcharge():
    old = make_property(condition=PropertyCondition.COSMETIC, square_feet=1000, year_built=1960)
    assert uw.estimate_repairs(old, AS_OF) == Decimal("24000.00")


def test_repair_estimate_defaults_to_today():
    prop = make_property(condition=PropertyCondition.TURNKEY, square_feet=1000, year_built=2020)
    assert uw.estimate_repairs(prop) == Decimal("2000.00")


def test_mao_follows_seventy_percent_rule():
    mao = uw.maximum_allowable_offer(Decimal("300000"), Decimal("50000"), Decimal("10000"))
    assert mao == Decimal("150000.00")


def test_mao_floors_at_zero_instead_of_going_negative():
    assert uw.maximum_allowable_offer(
        Decimal("100000"), Decimal("90000"), Decimal("10000")
    ) == Decimal("0.00")


def test_underwrite_produces_viable_deal():
    prop = make_property(square_feet=1600)
    result = uw.underwrite(prop, assignment_fee=Decimal("10000"), as_of=AS_OF)
    assert result.arv == Decimal("240000.00")
    assert result.repair_estimate == Decimal("60800.00")
    assert result.max_allowable_offer == Decimal("97200.00")
    assert result.assignment_fee == Decimal("10000")
    assert result.is_viable


def test_underwrite_rejects_fee_below_floor():
    with pytest.raises(uw.UnderwritingError, match="below the"):
        uw.underwrite(make_property(), assignment_fee=Decimal("100"), as_of=AS_OF)


def test_underwrite_trims_fee_to_keep_a_live_offer():
    # Heavy rehab consumes nearly all the 70% headroom, so the fee must shrink.
    prop = make_property(
        condition=PropertyCondition.HEAVY,
        square_feet=1600,
        assessed_value="170000",
        comparables=(),
    )
    result = uw.underwrite(prop, assignment_fee=Decimal("30000"), as_of=AS_OF)
    assert result.assignment_fee < Decimal("30000")
    assert result.assignment_fee >= uw.MIN_ASSIGNMENT_FEE
    assert result.max_allowable_offer > Decimal("0")


def test_underwrite_can_still_report_a_dead_deal():
    prop = make_property(
        condition=PropertyCondition.TEARDOWN,
        square_feet=2000,
        assessed_value="100000",
        comparables=(),
        address=make_address(street="9 Dead End"),
    )
    result = uw.underwrite(prop, assignment_fee=Decimal("10000"), as_of=AS_OF)
    assert result.max_allowable_offer == Decimal("0.00")
    assert not result.is_viable
