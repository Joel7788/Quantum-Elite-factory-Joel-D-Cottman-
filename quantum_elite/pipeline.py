"""End-to-end acquisition-to-disposition orchestrator.

Each lead flows: ingest -> enrich -> skip trace -> score -> underwrite -> offer
-> buyer match -> documents. A lead that fails a gate is rejected with a reason
and the run continues; a provider raising is recorded as a failure event rather
than aborting the whole run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from . import documents as docs
from . import matching, offers, scoring, underwriting
from .models import DealPacket, Lead, LeadStage
from .providers import (
    BuyerRepository,
    LeadSource,
    PropertyDataProvider,
    ProviderError,
    SkipTraceProvider,
)
from .telemetry import EventStatus, RunTelemetry

# Leads below this motivation score are not worth underwriting.
MIN_MOTIVATION_SCORE = Decimal("0.25")


@dataclass(frozen=True)
class PipelineConfig:
    min_motivation_score: Decimal = MIN_MOTIVATION_SCORE
    assignment_fee: Decimal = underwriting.DEFAULT_ASSIGNMENT_FEE
    require_reachable_contact: bool = True
    as_of: Optional[date] = None

    @property
    def effective_date(self) -> date:
        return self.as_of or date.today()


@dataclass
class PipelineResult:
    telemetry: RunTelemetry
    packets: list[DealPacket] = field(default_factory=list)

    @property
    def contracted(self) -> tuple[DealPacket, ...]:
        return tuple(p for p in self.packets if p.offer is not None)

    @property
    def assigned(self) -> tuple[DealPacket, ...]:
        return tuple(p for p in self.packets if p.is_closed_loop)

    @property
    def rejected(self) -> tuple[DealPacket, ...]:
        return tuple(p for p in self.packets if p.lead.stage is LeadStage.REJECTED)

    @property
    def projected_revenue(self) -> Decimal:
        return sum(
            (p.assignment.fee for p in self.assigned if p.assignment), Decimal("0")
        ).quantize(Decimal("0.01"))


class Pipeline:
    """Wires providers into the acquisition and disposition stages."""

    def __init__(
        self,
        lead_source: LeadSource,
        property_data: PropertyDataProvider,
        skip_trace: SkipTraceProvider,
        buyers: BuyerRepository,
        config: PipelineConfig | None = None,
    ):
        self.lead_source = lead_source
        self.property_data = property_data
        self.skip_trace = skip_trace
        self.buyers = buyers
        self.config = config or PipelineConfig()

    def run(self, run_id: str | None = None) -> PipelineResult:
        telemetry = RunTelemetry(
            run_id=run_id or uuid.uuid4().hex[:12], started_at=RunTelemetry.now()
        )
        result = PipelineResult(telemetry=telemetry)

        for lead in self.lead_source.fetch():
            telemetry.record(lead.lead_id, LeadStage.INGESTED, detail=self.lead_source.name)
            result.packets.append(self._process(lead, telemetry))

        telemetry.finish()
        return result

    def _process(self, lead: Lead, telemetry: RunTelemetry) -> DealPacket:
        packet = DealPacket(lead=lead)
        try:
            if not self._enrich(lead, telemetry):
                return packet
            if not self._qualify(lead, telemetry):
                return packet
            if not self._underwrite(lead, telemetry):
                return packet
            packet = self._make_offer(lead, packet, telemetry)
            if packet.offer is None:
                return packet
            packet = self._dispose(lead, packet, telemetry)
            return self._paper(packet, telemetry)
        except ProviderError as exc:
            telemetry.record(lead.lead_id, lead.stage, EventStatus.FAILED, str(exc))
            return packet

    def _enrich(self, lead: Lead, telemetry: RunTelemetry) -> bool:
        data = self.property_data.lookup(lead.address)
        if data is None:
            lead.reject("no property data available")
            telemetry.record(
                lead.lead_id, LeadStage.ENRICHED, EventStatus.REJECTED, lead.rejection_reason or ""
            )
            return False
        lead.property_data = data
        lead.advance(LeadStage.ENRICHED)
        telemetry.record(lead.lead_id, LeadStage.ENRICHED, detail=data.condition.value)

        lead.contacts = self.skip_trace.trace(lead.owner_name, lead.address)
        lead.advance(LeadStage.SKIP_TRACED)
        telemetry.record(
            lead.lead_id, LeadStage.SKIP_TRACED, detail=f"{len(lead.contacts)} contacts"
        )
        return True

    def _qualify(self, lead: Lead, telemetry: RunTelemetry) -> bool:
        breakdown = scoring.explain(lead)
        lead.motivation_score = breakdown.score
        lead.advance(LeadStage.SCORED)
        telemetry.record(
            lead.lead_id, LeadStage.SCORED, detail=f"{breakdown.score} ({breakdown.band})"
        )

        if breakdown.score < self.config.min_motivation_score:
            lead.reject(f"motivation {breakdown.score} below {self.config.min_motivation_score}")
            telemetry.record(
                lead.lead_id, LeadStage.SCORED, EventStatus.REJECTED, lead.rejection_reason or ""
            )
            return False
        if self.config.require_reachable_contact and lead.best_contact is None:
            lead.reject("no reachable contact")
            telemetry.record(
                lead.lead_id,
                LeadStage.SKIP_TRACED,
                EventStatus.REJECTED,
                lead.rejection_reason or "",
            )
            return False
        return True

    def _underwrite(self, lead: Lead, telemetry: RunTelemetry) -> bool:
        assert lead.property_data is not None
        try:
            result = underwriting.underwrite(
                lead.property_data,
                assignment_fee=self.config.assignment_fee,
                as_of=self.config.effective_date,
            )
        except underwriting.UnderwritingError as exc:
            lead.reject(str(exc))
            telemetry.record(
                lead.lead_id, LeadStage.UNDERWRITTEN, EventStatus.REJECTED, str(exc)
            )
            return False

        if not result.is_viable:
            lead.reject(f"no spread at MAO {result.max_allowable_offer}")
            telemetry.record(
                lead.lead_id,
                LeadStage.UNDERWRITTEN,
                EventStatus.REJECTED,
                lead.rejection_reason or "",
            )
            return False

        lead.underwriting = result
        lead.advance(LeadStage.UNDERWRITTEN)
        telemetry.record(
            lead.lead_id,
            LeadStage.UNDERWRITTEN,
            detail=f"ARV {result.arv} MAO {result.max_allowable_offer}",
        )
        return True

    def _make_offer(self, lead: Lead, packet: DealPacket, telemetry: RunTelemetry) -> DealPacket:
        assert lead.underwriting is not None and lead.motivation_score is not None
        try:
            offer = offers.generate_offer(
                lead, lead.underwriting, lead.motivation_score, as_of=self.config.effective_date
            )
        except offers.OfferError as exc:
            lead.reject(str(exc))
            telemetry.record(lead.lead_id, LeadStage.OFFER_SENT, EventStatus.REJECTED, str(exc))
            return packet

        lead.advance(LeadStage.OFFER_SENT)
        telemetry.record(lead.lead_id, LeadStage.OFFER_SENT, detail=str(offer.amount))
        lead.advance(LeadStage.UNDER_CONTRACT)
        telemetry.record(lead.lead_id, LeadStage.UNDER_CONTRACT, detail=str(offer.expires_on))
        return DealPacket(lead=lead, offer=offer)

    def _dispose(self, lead: Lead, packet: DealPacket, telemetry: RunTelemetry) -> DealPacket:
        assert packet.offer is not None and lead.underwriting is not None
        try:
            assignment = matching.assign_best_buyer(
                self.buyers.all_buyers(),
                lead.address.market_key,
                packet.offer,
                lead.underwriting,
            )
        except matching.MatchingError as exc:
            # The contract still stands; only the disposition side is unresolved.
            telemetry.record(lead.lead_id, LeadStage.ASSIGNED, EventStatus.REJECTED, str(exc))
            return packet

        lead.advance(LeadStage.ASSIGNED)
        telemetry.record(
            lead.lead_id,
            LeadStage.ASSIGNED,
            detail=f"{assignment.buyer.name} @ {assignment.match_score}",
        )
        return DealPacket(lead=lead, offer=packet.offer, assignment=assignment)

    def _paper(self, packet: DealPacket, telemetry: RunTelemetry) -> DealPacket:
        try:
            generated = docs.generate_documents(packet, as_of=self.config.effective_date)
        except docs.DocumentError as exc:
            telemetry.record(packet.lead.lead_id, packet.lead.stage, EventStatus.FAILED, str(exc))
            return packet
        telemetry.record(
            packet.lead.lead_id,
            packet.lead.stage,
            detail=f"documents: {', '.join(sorted(generated))}",
        )
        return packet.with_documents(generated)
