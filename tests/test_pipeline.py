from decimal import Decimal

from conftest import (
    AS_OF,
    DATA_DIR,
    make_address,
    make_buyer,
    make_contact,
    make_lead,
    make_property,
)

from quantum_elite import documents as docs
from quantum_elite import offers
from quantum_elite.models import DistressSignal, LeadStage, PropertyCondition
from quantum_elite.pipeline import Pipeline, PipelineConfig, PipelineResult
from quantum_elite.providers import InMemoryLeadSource, ProviderError
from quantum_elite.telemetry import EventStatus, RunTelemetry


class StubPropertyData:
    def __init__(self, by_street=None, raises=False):
        self._by_street = by_street or {}
        self._raises = raises

    def lookup(self, address):
        if self._raises:
            raise ProviderError("property provider unavailable")
        return self._by_street.get(address.street)


class StubSkipTrace:
    def __init__(self, contacts=(), raises=False):
        self._contacts = tuple(contacts)
        self._raises = raises

    def trace(self, owner_name, address):
        if self._raises:
            raise ProviderError("skip trace quota exceeded")
        return self._contacts


class StubBuyers:
    def __init__(self, buyers=()):
        self._buyers = tuple(buyers)

    def all_buyers(self):
        return self._buyers


def build(leads, property_data=None, skip_trace=None, buyers=None, config=None):
    return Pipeline(
        lead_source=InMemoryLeadSource(leads, name="stub_source"),
        property_data=property_data or StubPropertyData({"118 Halyard Ln": make_property()}),
        skip_trace=skip_trace or StubSkipTrace((make_contact(),)),
        buyers=buyers or StubBuyers((make_buyer(),)),
        config=config or PipelineConfig(as_of=AS_OF),
    )


def test_config_effective_date_defaults_to_today():
    assert PipelineConfig().effective_date is not None
    assert PipelineConfig(as_of=AS_OF).effective_date == AS_OF


def test_full_happy_path_reaches_assignment_with_documents():
    lead = make_lead()
    result = build([lead]).run(run_id="run-happy")
    packet = result.packets[0]

    assert result.telemetry.run_id == "run-happy"
    assert packet.lead.stage is LeadStage.ASSIGNED
    assert packet.is_closed_loop
    assert packet.offer is not None and packet.offer.amount > Decimal("0")
    assert packet.assignment is not None and packet.assignment.buyer.buyer_id == "CB-TEST"
    assert set(packet.documents) == {
        docs.PURCHASE_AGREEMENT,
        docs.INSPECTION_ADDENDUM,
        docs.ASSIGNMENT_AGREEMENT,
        docs.CLOSING_PACKAGE,
    }
    assert result.assigned == (packet,)
    assert result.contracted == (packet,)
    assert result.rejected == ()
    assert result.projected_revenue == Decimal("10000.00")
    assert result.telemetry.health == "nominal"
    assert result.telemetry.finished_at is not None


def test_lead_without_property_data_is_rejected_at_enrichment():
    lead = make_lead(address=make_address(street="404 Nowhere"))
    result = build([lead]).run()
    assert lead.stage is LeadStage.REJECTED
    assert lead.rejection_reason == "no property data available"
    assert result.rejected and not result.contracted
    stages = [(e.stage, e.status) for e in result.telemetry.events_for(lead.lead_id)]
    assert (LeadStage.ENRICHED, EventStatus.REJECTED) in stages


def test_low_motivation_lead_is_rejected_before_underwriting():
    lead = make_lead(signals=(DistressSignal.EXPIRED_LISTING,), days_on_market=None)
    result = build([lead]).run()
    assert lead.stage is LeadStage.REJECTED
    assert "below 0.25" in (lead.rejection_reason or "")
    assert lead.underwriting is None
    assert result.telemetry.rejections()


def test_unreachable_lead_is_rejected_when_contact_is_required():
    lead = make_lead()
    result = build([lead], skip_trace=StubSkipTrace(())).run()
    assert lead.rejection_reason == "no reachable contact"
    assert result.rejected


def test_contact_requirement_can_be_disabled():
    lead = make_lead()
    result = build(
        [lead],
        skip_trace=StubSkipTrace(()),
        config=PipelineConfig(as_of=AS_OF, require_reachable_contact=False),
    ).run()
    assert lead.stage is LeadStage.ASSIGNED
    assert result.assigned


def test_dead_deal_is_rejected_during_underwriting():
    prop = make_property(
        condition=PropertyCondition.TEARDOWN,
        square_feet=2000,
        assessed_value="100000",
        comparables=(),
    )
    lead = make_lead()
    result = build([lead], property_data=StubPropertyData({"118 Halyard Ln": prop})).run()
    assert lead.stage is LeadStage.REJECTED
    assert "no spread at MAO" in (lead.rejection_reason or "")
    assert result.telemetry.rejections()


def test_underwriting_error_rejects_rather_than_crashing():
    lead = make_lead()
    result = build(
        [lead],
        config=PipelineConfig(as_of=AS_OF, assignment_fee=Decimal("10")),
    ).run()
    assert lead.stage is LeadStage.REJECTED
    assert "below the" in (lead.rejection_reason or "")
    assert result.telemetry.failures() == ()


def test_unmatched_deal_stays_under_contract():
    lead = make_lead()
    result = build([lead], buyers=StubBuyers(())).run()
    packet = result.packets[0]
    assert lead.stage is LeadStage.UNDER_CONTRACT
    assert packet.offer is not None
    assert packet.assignment is None
    assert not packet.is_closed_loop
    assert result.contracted == (packet,)
    assert result.assigned == ()
    assert set(packet.documents) == {docs.PURCHASE_AGREEMENT, docs.INSPECTION_ADDENDUM}


def test_provider_failure_is_recorded_and_other_leads_continue():
    failing = make_lead(lead_id="QE-FAIL")
    healthy = make_lead(lead_id="QE-OK")

    class FlakySkipTrace:
        def trace(self, owner_name, address):
            if owner_name == "boom":
                raise ProviderError("skip trace quota exceeded")
            return (make_contact(),)

    failing.owner_name = "boom"
    result = build([failing, healthy], skip_trace=FlakySkipTrace()).run()
    assert result.telemetry.health == "degraded"
    assert [e.lead_id for e in result.telemetry.failures()] == ["QE-FAIL"]
    assert healthy.stage is LeadStage.ASSIGNED


def test_property_provider_failure_is_isolated_per_lead():
    lead = make_lead()
    result = build([lead], property_data=StubPropertyData(raises=True)).run()
    assert result.telemetry.failures()[0].detail == "property provider unavailable"
    assert result.packets[0].offer is None


def test_document_failure_is_recorded_without_losing_the_contract(monkeypatch):
    def explode(packet, as_of=None):
        raise docs.DocumentError("template drift")

    monkeypatch.setattr("quantum_elite.pipeline.docs.generate_documents", explode)
    lead = make_lead()
    result = build([lead]).run()
    packet = result.packets[0]
    assert packet.offer is not None
    assert packet.documents == {}
    assert result.telemetry.failures()[0].detail == "template drift"


def test_empty_result_rollups_are_safe():
    result = PipelineResult(telemetry=RunTelemetry(run_id="r", started_at=RunTelemetry.now()))
    assert result.projected_revenue == Decimal("0.00")
    assert result.contracted == () and result.assigned == () and result.rejected == ()


def test_stage_ordering_is_recorded_for_a_full_deal():
    lead = make_lead()
    result = build([lead]).run()
    stages = [e.stage for e in result.telemetry.events_for(lead.lead_id)]
    assert stages[:6] == [
        LeadStage.INGESTED,
        LeadStage.ENRICHED,
        LeadStage.SKIP_TRACED,
        LeadStage.SCORED,
        LeadStage.UNDERWRITTEN,
        LeadStage.OFFER_SENT,
    ]
    assert LeadStage.ASSIGNED in stages


def test_bundled_fixture_run_is_deterministic():
    from quantum_elite.cli import build_pipeline

    config = PipelineConfig(as_of=AS_OF)
    first = build_pipeline(DATA_DIR, config).run()
    second = build_pipeline(DATA_DIR, config).run()
    assert first.telemetry.health == "nominal"
    assert [p.lead.stage for p in first.packets] == [p.lead.stage for p in second.packets]
    assert first.projected_revenue == second.projected_revenue == Decimal("10000.00")


def test_offer_engine_refusal_rejects_the_lead_without_a_contract(monkeypatch):
    lead = make_lead()

    def refuse(*args, **kwargs):
        raise offers.OfferError("spread evaporated at offer time")

    monkeypatch.setattr("quantum_elite.pipeline.offers.generate_offer", refuse)
    result = build([lead]).run()
    packet = result.packets[0]
    assert packet.offer is None
    assert packet.lead.stage is LeadStage.REJECTED
    assert packet.lead.rejection_reason == "spread evaporated at offer time"
    assert result.contracted == ()
    assert [e.status for e in result.telemetry.events_for(lead.lead_id)][-1] is EventStatus.REJECTED
