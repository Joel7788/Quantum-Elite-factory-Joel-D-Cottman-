import json
from decimal import Decimal

import pytest
from conftest import DATA_DIR, make_address, make_lead

from quantum_elite import providers as prov
from quantum_elite.models import DistressSignal, PropertyCondition

LEAD_PAYLOAD = {
    "lead_id": "QE-9001",
    "address": {
        "street": "5 Beacon Row",
        "city": "Norfolk",
        "state": "VA",
        "postal_code": 23503,
    },
    "owner_name": "Dana Reed",
    "source": "public_records",
    "distress_signals": ["probate", "vacant"],
    "asking_price": "150000",
    "days_on_market": 45,
}

PROPERTY_PAYLOAD = {
    "address": {"street": "5 Beacon Row", "city": "Norfolk", "state": "VA", "postal_code": "23503"},
    "square_feet": 1500,
    "bedrooms": 3,
    "bathrooms": "2",
    "year_built": 1998,
    "lot_size_sqft": 6000,
    "condition": "moderate",
    "assessed_value": "205000",
    "comparables": [
        {
            "address": {
                "street": "7 Beacon Row",
                "city": "Norfolk",
                "state": "VA",
                "postal_code": "23503",
            },
            "sold_price": "225000",
            "square_feet": 1500,
            "sold_on": "2026-05-01",
            "distance_miles": "0.3",
        }
    ],
}

BUYER_PAYLOAD = {
    "buyer_id": "CB-77",
    "name": "Beacon Cash",
    "markets": ["norfolk|VA"],
    "min_price": "50000",
    "max_price": "300000",
    "max_repair_tolerance": "100000",
    "proof_of_funds": True,
    "close_days": 12,
}


def write_json(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def test_json_implementations_satisfy_the_protocols(tmp_path):
    assert isinstance(prov.JsonLeadSource(write_json(tmp_path, "l.json", [])), prov.LeadSource)
    assert isinstance(
        prov.JsonPropertyDataProvider(write_json(tmp_path, "p.json", [])),
        prov.PropertyDataProvider,
    )
    assert isinstance(
        prov.JsonSkipTraceProvider(write_json(tmp_path, "s.json", [])), prov.SkipTraceProvider
    )
    assert isinstance(
        prov.JsonBuyerRepository(write_json(tmp_path, "b.json", [])), prov.BuyerRepository
    )


def test_parse_lead_coerces_types():
    lead = prov.parse_lead(LEAD_PAYLOAD)
    assert lead.lead_id == "QE-9001"
    assert lead.address.postal_code == "23503"
    assert lead.distress_signals == (DistressSignal.PROBATE, DistressSignal.VACANT)
    assert lead.asking_price == Decimal("150000")


def test_parse_lead_defaults_optional_fields():
    payload = {k: v for k, v in LEAD_PAYLOAD.items() if k not in {"source", "asking_price"}}
    lead = prov.parse_lead(payload)
    assert lead.source == "unknown"
    assert lead.asking_price is None


@pytest.mark.parametrize("missing", ["lead_id", "address", "owner_name"])
def test_parse_lead_reports_missing_field(missing):
    payload = {k: v for k, v in LEAD_PAYLOAD.items() if k != missing}
    with pytest.raises(prov.ProviderError, match=missing):
        prov.parse_lead(payload)


def test_parse_lead_reports_missing_address_field():
    payload = {**LEAD_PAYLOAD, "address": {"city": "Norfolk", "state": "VA", "postal_code": "1"}}
    with pytest.raises(prov.ProviderError, match="address payload missing field: street"):
        prov.parse_lead(payload)


def test_parse_lead_rejects_unknown_enum_value():
    payload = {**LEAD_PAYLOAD, "distress_signals": ["haunted"]}
    with pytest.raises(prov.ProviderError, match="unknown DistressSignal"):
        prov.parse_lead(payload)


def test_parse_property_data_builds_comparables():
    data = prov.parse_property_data(PROPERTY_PAYLOAD)
    assert data.condition is PropertyCondition.MODERATE
    assert data.mortgage_balance == Decimal("0")
    assert len(data.comparables) == 1
    assert data.comparables[0].price_per_square_foot == Decimal("150")


def test_parse_property_data_reports_missing_field():
    payload = {k: v for k, v in PROPERTY_PAYLOAD.items() if k != "condition"}
    with pytest.raises(prov.ProviderError, match="property payload missing field: condition"):
        prov.parse_property_data(payload)


def test_parse_buyer_and_contact():
    buyer = prov.parse_buyer(BUYER_PAYLOAD)
    assert buyer.deals_closed == 0
    assert buyer.covers_market("norfolk|VA")

    contact = prov.parse_contact({"name": "Dana"})
    assert contact.confidence == Decimal("0.5")
    assert not contact.is_reachable

    with pytest.raises(prov.ProviderError, match="buyer payload missing field: markets"):
        prov.parse_buyer({k: v for k, v in BUYER_PAYLOAD.items() if k != "markets"})
    with pytest.raises(prov.ProviderError, match="contact payload missing field: name"):
        prov.parse_contact({"phone": "1"})


def test_load_json_error_paths(tmp_path):
    with pytest.raises(prov.ProviderError, match="not found"):
        prov.load_json(tmp_path / "absent.json")

    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    with pytest.raises(prov.ProviderError, match="not valid JSON"):
        prov.load_json(bad)

    not_a_list = write_json(tmp_path, "obj.json", {"a": 1})
    with pytest.raises(prov.ProviderError, match="expected a JSON list"):
        prov.load_json(not_a_list)


def test_json_lead_source_yields_leads(tmp_path):
    source = prov.JsonLeadSource(write_json(tmp_path, "leads.json", [LEAD_PAYLOAD]), name="zillow")
    leads = list(source.fetch())
    assert source.name == "zillow"
    assert [lead.lead_id for lead in leads] == ["QE-9001"]


def test_in_memory_lead_source_replays_leads():
    lead = make_lead()
    source = prov.InMemoryLeadSource([lead])
    assert list(source.fetch()) == [lead]
    assert list(source.fetch()) == [lead]
    assert source.name == "in_memory"


def test_json_property_provider_lookup_hit_and_miss(tmp_path):
    provider = prov.JsonPropertyDataProvider(write_json(tmp_path, "p.json", [PROPERTY_PAYLOAD]))
    found = provider.lookup(make_address(street="5 Beacon Row"))
    assert found is not None and found.square_feet == 1500
    assert provider.lookup(make_address(street="404 Nowhere")) is None


def test_json_skip_trace_is_case_insensitive_and_merges_contacts(tmp_path):
    payload = [
        {"owner_name": "Dana Reed", "contacts": [{"name": "Dana Reed", "phone": "1"}]},
        {"owner_name": " dana reed ", "contacts": [{"name": "D. Reed", "email": "d@r.com"}]},
    ]
    provider = prov.JsonSkipTraceProvider(write_json(tmp_path, "s.json", payload))
    contacts = provider.trace("DANA REED", make_address())
    assert len(contacts) == 2
    assert provider.trace("Nobody", make_address()) == ()


def test_json_skip_trace_reports_missing_field(tmp_path):
    path = write_json(tmp_path, "s.json", [{"contacts": []}])
    with pytest.raises(prov.ProviderError, match="skip trace payload missing field: owner_name"):
        prov.JsonSkipTraceProvider(path)


def test_bundled_fixtures_parse():
    leads = list(prov.JsonLeadSource(DATA_DIR / "leads.json").fetch())
    buyers = prov.JsonBuyerRepository(DATA_DIR / "buyers.json").all_buyers()
    properties = prov.JsonPropertyDataProvider(DATA_DIR / "properties.json")
    skip = prov.JsonSkipTraceProvider(DATA_DIR / "skip_trace.json")
    assert leads and buyers
    assert properties.lookup(leads[0].address) is not None
    assert skip.trace(leads[0].owner_name, leads[0].address)
