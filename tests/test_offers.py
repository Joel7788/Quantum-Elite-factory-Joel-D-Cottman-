from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import AS_OF, make_lead

from quantum_elite import offers
from quantum_elite.models import Underwriting


def underwriting(mao="100000", arv="240000", repairs="60000", fee="10000"):
    return Underwriting(
        arv=Decimal(arv),
        repair_estimate=Decimal(repairs),
        max_allowable_offer=Decimal(mao),
        assignment_fee=Decimal(fee),
        confidence=Decimal("0.9"),
    )


@pytest.mark.parametrize(
    "score, ratio",
    [("0.90", "0.88"), ("0.65", "0.88"), ("0.50", "0.94"), ("0.35", "0.94"), ("0.10", "1.00")],
)
def test_anchor_ratio_by_motivation(score, ratio):
    assert offers.anchor_ratio(Decimal(score)) == Decimal(ratio)


def test_earnest_money_is_one_percent_with_a_floor():
    assert offers.earnest_money(Decimal("100000")) == Decimal("1000.00")
    assert offers.earnest_money(Decimal("10000")) == Decimal("500")


def test_high_motivation_opens_below_mao():
    offer = offers.generate_offer(make_lead(), underwriting(), Decimal("0.80"), as_of=AS_OF)
    assert offer.amount == Decimal("88000.00")
    assert offer.amount < underwriting().max_allowable_offer


def test_low_motivation_offers_at_mao_but_never_above():
    offer = offers.generate_offer(make_lead(), underwriting(), Decimal("0.10"), as_of=AS_OF)
    assert offer.amount == Decimal("100000.00")


def test_offer_never_exceeds_asking_price():
    lead = make_lead(asking_price="75000")
    offer = offers.generate_offer(lead, underwriting(), Decimal("0.10"), as_of=AS_OF)
    assert offer.amount == Decimal("75000.00")


def test_offer_terms_and_expiry():
    offer = offers.generate_offer(make_lead(), underwriting(), Decimal("0.50"), as_of=AS_OF)
    assert offer.lead_id == "QE-TEST"
    assert offer.inspection_days == offers.DEFAULT_INSPECTION_DAYS
    assert offer.close_days == offers.DEFAULT_CLOSE_DAYS
    assert offer.expires_on == AS_OF + timedelta(days=offers.OFFER_VALID_DAYS)
    assert offer.earnest_money == Decimal("940.00")


def test_offer_defaults_expiry_from_today():
    offer = offers.generate_offer(make_lead(), underwriting(), Decimal("0.50"))
    assert offer.expires_on == date.today() + timedelta(days=offers.OFFER_VALID_DAYS)


def test_no_offer_without_viable_spread():
    dead = underwriting(mao="0", arv="100000", repairs="90000")
    with pytest.raises(offers.OfferError, match="no viable spread"):
        offers.generate_offer(make_lead(), dead, Decimal("0.90"), as_of=AS_OF)
