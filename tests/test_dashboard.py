from decimal import Decimal

from conftest import AS_OF, make_buyer, make_contact, make_lead, make_property

from quantum_elite import dashboard
from quantum_elite.models import LeadStage
from quantum_elite.pipeline import Pipeline, PipelineConfig, PipelineResult
from quantum_elite.providers import InMemoryLeadSource
from quantum_elite.telemetry import EventStatus, RunTelemetry


class Stub:
    def __init__(self, prop=None, contacts=(), buyers=()):
        self._prop = prop
        self._contacts = contacts
        self._buyers = buyers

    def lookup(self, address):
        return self._prop

    def trace(self, owner_name, address):
        return self._contacts

    def all_buyers(self):
        return self._buyers


def run_result(buyers=(), street="118 Halyard Ln"):
    stub = Stub(prop=make_property(), contacts=(make_contact(),), buyers=buyers)
    pipeline = Pipeline(
        lead_source=InMemoryLeadSource([make_lead()], name="stub"),
        property_data=stub,
        skip_trace=stub,
        buyers=stub,
        config=PipelineConfig(as_of=AS_OF),
    )
    return pipeline.run(run_id="run-dash")


def test_dashboard_renders_standalone_html_with_run_metrics():
    html = dashboard.render_dashboard(run_result(buyers=(make_buyer(name="Harborline"),)))
    assert html.startswith("<!DOCTYPE html>")
    # Standalone: inline styles only, no external stylesheet or script fetches.
    assert "<style>" in html
    assert "<link" not in html and "<script" not in html
    assert "run-dash" in html
    assert "QUANTUM ELITE FACTORY" in html
    assert "JOEL D COTTMAN" in html
    assert "Harborline" in html
    assert "$10,000.00" in html


def test_dashboard_uses_neon_palette_and_health_colors():
    html = dashboard.render_dashboard(run_result())
    assert dashboard.PALETTE["background"] in html
    assert dashboard.PALETTE["cyan"] in html
    assert dashboard.HEALTH_COLORS["nominal"] in html


def test_degraded_run_is_flagged_in_red():
    result = run_result()
    result.telemetry.record("QE-TEST", LeadStage.ENRICHED, EventStatus.FAILED, "provider down")
    html = dashboard.render_dashboard(result)
    assert "DEGRADED" in html
    assert dashboard.HEALTH_COLORS["degraded"] in html
    assert dashboard.STATUS_COLORS[EventStatus.FAILED] in html


def test_every_stage_appears_in_throughput_table():
    html = dashboard.render_dashboard(run_result())
    for stage in LeadStage:
        assert f"<td>{stage.value}</td>" in html


def test_empty_run_renders_placeholder_rows():
    empty = PipelineResult(telemetry=RunTelemetry(run_id="idle", started_at=RunTelemetry.now()))
    html = dashboard.render_dashboard(empty)
    assert "no deals in this run" in html
    assert "no telemetry recorded" in html
    assert "IDLE" in html


def test_untrusted_values_are_html_escaped():
    result = run_result()
    result.telemetry.record("<script>x</script>", LeadStage.SCORED, detail='"evil" & co')
    html = dashboard.render_dashboard(result)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "&quot;evil&quot; &amp; co" in html


def test_unmatched_deal_is_shown_as_unmatched():
    html = dashboard.render_dashboard(run_result(buyers=()))
    assert "unmatched" in html


def test_footer_states_documents_are_drafts():
    html = dashboard.render_dashboard(run_result())
    assert "drafts for attorney review" in html


def test_write_dashboard_creates_parent_directories(tmp_path):
    path = dashboard.write_dashboard(run_result(), tmp_path / "nested" / "telemetry.html")
    assert path.is_file()
    assert path.read_text().startswith("<!DOCTYPE html>")


def test_money_helper_formats_decimals():
    assert dashboard._money(Decimal("10000")) == "$10,000.00"
