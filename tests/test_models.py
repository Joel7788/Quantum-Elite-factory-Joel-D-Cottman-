from decimal import Decimal

import pytest
from conftest import make_address, make_buyer, make_comparable, make_contact, make_lead

from quantum_elite.models import (
    Contact,
    DealPacket,
    LeadStage,
    PropertyCondition,
    PropertyData,
    Underwriting,
)


def test_address_one_line_and_market_key():
    address = make_address(city="Norfolk", state="VA")
    assert address.one_line == "118 Halyard Ln, Norfolk, VA 23503"
    assert address.market_key == "norfolk|VA"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"street": "   "}, "street is required"),
        ({"state": "Virginia"}, "2-letter code"),
    ],
)
def test_address_rejects_bad_input(kwargs, message):
    with pytest.raises(ValueError, match=message):
        make_address(**kwargs)


def test_comparable_price_per_square_foot():
    comp = make_comparable(sold_price="240000", square_feet=1600)
    assert comp.price_per_square_foot == Decimal("150")


@pytest.mark.parametrize("kwargs", [{"square_feet": 0}, {"sold_price": "0"}])
def test_comparable_rejects_nonpositive_values(kwargs):
    with pytest.raises(ValueError):
        make_comparable(**kwargs)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"mortgage_balance": Decimal("-1")}, "mortgage_balance"),
        ({"square_feet": 0}, "square_feet"),
    ],
)
def test_property_data_validates_inputs(kwargs, message):
    fields = {
        "address": make_address(),
        "square_feet": 1000,
        "bedrooms": 3,
        "bathrooms": Decimal("2"),
        "year_built": 1990,
        "lot_size_sqft": 5000,
        "condition": PropertyCondition.COSMETIC,
        "assessed_value": Decimal("100000"),
        **kwargs,
    }
    with pytest.raises(ValueError, match=message):
        PropertyData(**fields)


def test_contact_reachability_and_confidence_bounds():
    assert make_contact(phone="757-555-0101").is_reachable
    assert make_contact(phone=None, email="a@b.com").is_reachable
    assert not make_contact(phone=None, email=None).is_reachable
    with pytest.raises(ValueError, match="confidence"):
        Contact(name="x", phone="1", confidence=Decimal("1.5"))


def test_best_contact_prefers_highest_confidence_reachable():
    unreachable = make_contact(name="ghost", phone=None, email=None, confidence="0.99")
    weak = make_contact(name="weak", phone="1", confidence="0.2")
    strong = make_contact(name="strong", phone="2", confidence="0.8")
    lead = make_lead(contacts=(unreachable, weak, strong))
    assert lead.best_contact is strong


def test_best_contact_is_none_without_reachable_contacts():
    assert make_lead(contacts=()).best_contact is None


def test_lead_advance_then_reject_is_terminal():
    lead = make_lead()
    lead.advance(LeadStage.ENRICHED)
    assert lead.stage is LeadStage.ENRICHED
    lead.reject("no spread")
    assert lead.stage is LeadStage.REJECTED
    assert lead.rejection_reason == "no spread"
    with pytest.raises(ValueError, match="cannot advance"):
        lead.advance(LeadStage.SCORED)


def test_underwriting_spread_and_viability():
    viable = Underwriting(
        arv=Decimal("240000"),
        repair_estimate=Decimal("60000"),
        max_allowable_offer=Decimal("100000"),
        assignment_fee=Decimal("10000"),
        confidence=Decimal("0.9"),
    )
    assert viable.spread == Decimal("80000")
    assert viable.is_viable

    dead = Underwriting(
        arv=Decimal("100000"),
        repair_estimate=Decimal("60000"),
        max_allowable_offer=Decimal("0"),
        assignment_fee=Decimal("10000"),
        confidence=Decimal("0.4"),
    )
    assert not dead.is_viable


def test_buyer_market_coverage_and_price_band_validation():
    buyer = make_buyer(markets=("norfolk|VA",))
    assert buyer.covers_market("norfolk|VA")
    assert not buyer.covers_market("richmond|VA")
    with pytest.raises(ValueError, match="min_price"):
        make_buyer(min_price="500000", max_price="100000")


def test_deal_packet_closed_loop_and_document_merge():
    packet = DealPacket(lead=make_lead())
    assert not packet.is_closed_loop
    merged = packet.with_documents({"purchase_agreement": "body"})
    assert merged.documents == {"purchase_agreement": "body"}
    # with_documents returns a copy; the original packet is untouched.
    assert packet.documents == {}
    assert merged.with_documents({"addendum": "b"}).documents.keys() == {
        "purchase_agreement",
        "addendum",
    }
