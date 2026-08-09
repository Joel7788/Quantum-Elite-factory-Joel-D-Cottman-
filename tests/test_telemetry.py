from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quantum_elite.models import LeadStage
from quantum_elite.telemetry import EventStatus, RunTelemetry, StageEvent

START = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def telemetry():
    return RunTelemetry(run_id="run-1", started_at=START)


def test_record_appends_events_in_order():
    run = telemetry()
    first = run.record("QE-1", LeadStage.INGESTED, detail="json_file")
    second = run.record("QE-2", LeadStage.INGESTED)
    assert run.events == [first, second]
    assert first.detail == "json_file"
    assert first.status is EventStatus.OK


def test_stage_event_terminality():
    ok = StageEvent("QE-1", LeadStage.SCORED, EventStatus.OK, "", START)
    rejected = StageEvent("QE-1", LeadStage.SCORED, EventStatus.REJECTED, "cold", START)
    assert not ok.is_terminal
    assert rejected.is_terminal


def test_duration_uses_finish_time_when_finished():
    run = telemetry()
    run.finished_at = START + timedelta(milliseconds=1500)
    assert run.duration_seconds == Decimal("1.5")


def test_duration_is_live_until_finished():
    run = RunTelemetry(run_id="run-2", started_at=RunTelemetry.now())
    assert run.finished_at is None
    assert run.duration_seconds >= Decimal("0")
    run.finish()
    assert run.finished_at is not None


def test_lead_ids_are_deduplicated_in_first_seen_order():
    run = telemetry()
    for lead_id in ("QE-2", "QE-1", "QE-2"):
        run.record(lead_id, LeadStage.INGESTED)
    assert run.lead_ids == ("QE-2", "QE-1")


def test_events_for_filters_by_lead():
    run = telemetry()
    run.record("QE-1", LeadStage.INGESTED)
    run.record("QE-2", LeadStage.INGESTED)
    run.record("QE-1", LeadStage.SCORED)
    assert [e.stage for e in run.events_for("QE-1")] == [LeadStage.INGESTED, LeadStage.SCORED]


def test_stage_counts_only_count_successful_events():
    run = telemetry()
    run.record("QE-1", LeadStage.SCORED)
    run.record("QE-2", LeadStage.SCORED)
    run.record("QE-3", LeadStage.SCORED, EventStatus.REJECTED, "cold")
    assert run.stage_counts() == {LeadStage.SCORED: 2}


def test_failures_rejections_and_health_rollups():
    idle = telemetry()
    assert idle.health == "idle"

    nominal = telemetry()
    nominal.record("QE-1", LeadStage.SCORED)
    nominal.record("QE-2", LeadStage.SCORED, EventStatus.REJECTED, "cold")
    assert nominal.health == "nominal"
    assert len(nominal.rejections()) == 1
    assert nominal.failures() == ()

    degraded = telemetry()
    degraded.record("QE-3", LeadStage.ENRICHED, EventStatus.FAILED, "provider down")
    assert degraded.health == "degraded"
    assert degraded.failures()[0].detail == "provider down"


def test_now_is_timezone_aware_utc():
    assert RunTelemetry.now().tzinfo == timezone.utc
