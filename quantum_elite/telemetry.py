"""Execution telemetry: per-stage events and run-level rollups."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from .models import LeadStage


class EventStatus(enum.Enum):
    OK = "ok"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class StageEvent:
    lead_id: str
    stage: LeadStage
    status: EventStatus
    detail: str
    at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.status is not EventStatus.OK


@dataclass
class RunTelemetry:
    """Append-only event log for one pipeline run, plus derived rollups."""

    run_id: str
    started_at: datetime
    events: list[StageEvent] = field(default_factory=list)
    finished_at: Optional[datetime] = None

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def record(
        self,
        lead_id: str,
        stage: LeadStage,
        status: EventStatus = EventStatus.OK,
        detail: str = "",
    ) -> StageEvent:
        event = StageEvent(
            lead_id=lead_id, stage=stage, status=status, detail=detail, at=self.now()
        )
        self.events.append(event)
        return event

    def finish(self) -> None:
        self.finished_at = self.now()

    @property
    def duration_seconds(self) -> Decimal:
        end = self.finished_at or self.now()
        return Decimal(str(round((end - self.started_at).total_seconds(), 3)))

    @property
    def lead_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(event.lead_id for event in self.events))

    def events_for(self, lead_id: str) -> tuple[StageEvent, ...]:
        return tuple(event for event in self.events if event.lead_id == lead_id)

    def stage_counts(self) -> dict[LeadStage, int]:
        counts: dict[LeadStage, int] = {}
        for event in self.events:
            if event.status is EventStatus.OK:
                counts[event.stage] = counts.get(event.stage, 0) + 1
        return counts

    def failures(self) -> tuple[StageEvent, ...]:
        return tuple(event for event in self.events if event.status is EventStatus.FAILED)

    def rejections(self) -> tuple[StageEvent, ...]:
        return tuple(event for event in self.events if event.status is EventStatus.REJECTED)

    @property
    def health(self) -> str:
        """Overall run health used to colour the telemetry dashboard."""
        if self.failures():
            return "degraded"
        if not self.events:
            return "idle"
        return "nominal"
