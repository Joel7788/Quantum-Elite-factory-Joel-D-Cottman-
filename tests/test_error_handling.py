"""Error-propagation contracts: nothing fails quietly."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from conftest import AS_OF, DATA_DIR, make_buyer, make_contact, make_lead, make_property

from quantum_elite import cli, providers, service
from quantum_elite.pipeline import Pipeline, PipelineConfig, PipelineError
from quantum_elite.providers import InMemoryLeadSource, ProviderError
from quantum_elite.telemetry import RunTelemetry


class RaisingSkipTrace:
    def __init__(self, exc):
        self._exc = exc

    def trace(self, owner_name, address):
        raise self._exc


class StubPropertyData:
    def lookup(self, address):
        return make_property(address=address)


class StubBuyers:
    def all_buyers(self):
        return (make_buyer(),)


class RaisingLeadSource:
    name = "raising_source"

    def __init__(self, leads, exc):
        self._leads = tuple(leads)
        self._exc = exc

    def fetch(self):
        yield from self._leads
        raise self._exc


def build(lead_source, skip_trace=None):
    return Pipeline(
        lead_source=lead_source,
        property_data=StubPropertyData(),
        skip_trace=skip_trace or RaisingSkipTrace(ProviderError("quota")),
        buyers=StubBuyers(),
        config=PipelineConfig(as_of=AS_OF),
    )


def write_json(path, payload):
    path.write_text(json.dumps(payload))
    return path


BAD_PROPERTY_PAYLOADS = [
    ({"square_feet": "not-a-number"}, "invalid field"),
    ({"assessed_value": "twelve dollars"}, "invalid field"),
    ({"condition": "pristine"}, "unknown PropertyCondition"),
    ({"square_feet": None}, "invalid field"),
]


def property_payload(**overrides):
    payload = {
        "address": {
            "street": "118 Halyard Ln",
            "city": "Norfolk",
            "state": "VA",
            "postal_code": "23503",
        },
        "square_feet": 1600,
        "bedrooms": 3,
        "bathrooms": "2",
        "year_built": 2005,
        "lot_size_sqft": 6000,
        "condition": "moderate",
        "assessed_value": "210000",
        "comparables": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("overrides, message", BAD_PROPERTY_PAYLOADS)
def test_unparsable_property_fields_become_provider_errors(overrides, message):
    with pytest.raises(ProviderError, match=message):
        providers.parse_property_data(property_payload(**overrides))


def test_unparsable_comparable_date_becomes_a_provider_error():
    comparable = {
        "address": property_payload()["address"],
        "sold_price": "240000",
        "square_feet": 1600,
        "sold_on": "05/01/2026",
        "distance_miles": "0.4",
    }
    with pytest.raises(ProviderError, match="invalid field"):
        providers.parse_property_data(property_payload(comparables=[comparable]))


def test_model_validation_failures_become_provider_errors():
    with pytest.raises(ProviderError, match="invalid field"):
        providers.parse_property_data(property_payload(square_feet=0))


def test_non_object_records_are_rejected(tmp_path):
    path = write_json(tmp_path / "leads.json", [{"lead_id": "QE-1"}, "nope"])
    with pytest.raises(ProviderError, match=r"leads.json\[1\], got str"):
        providers.load_json(path)


def test_unreadable_data_file_becomes_a_provider_error(tmp_path):
    directory = tmp_path / "leads.json"
    directory.mkdir()
    with pytest.raises(ProviderError, match="unreadable"):
        providers.load_json(directory)


def test_duplicate_property_records_are_rejected_instead_of_overwriting(tmp_path):
    path = write_json(
        tmp_path / "properties.json",
        [property_payload(), property_payload(assessed_value="999999")],
    )
    with pytest.raises(ProviderError, match="duplicate property record"):
        providers.JsonPropertyDataProvider(path)


def test_unexpected_stage_error_is_recorded_and_the_run_continues():
    leads = [make_lead(lead_id="QE-1"), make_lead(lead_id="QE-2")]
    pipeline = build(
        InMemoryLeadSource(leads, name="stub"),
        skip_trace=RaisingSkipTrace(TimeoutError("skip trace socket timeout")),
    )
    result = pipeline.run(run_id="run-unexpected")

    failures = result.telemetry.failures()
    assert [event.lead_id for event in failures] == ["QE-1", "QE-2"]
    assert "unhandled TimeoutError" in failures[0].detail
    assert result.telemetry.health == "degraded"


def test_lead_source_failure_still_finishes_telemetry():
    pipeline = build(
        RaisingLeadSource([make_lead()], ProviderError("lead feed died")),
        skip_trace=RaisingSkipTrace(ProviderError("quota")),
    )
    with pytest.raises(ProviderError, match="lead feed died"):
        pipeline.run(run_id="run-halted")


def test_broken_stage_contract_raises_instead_of_being_stripped_by_dash_o():
    pipeline = build(InMemoryLeadSource([make_lead()], name="stub"))
    telemetry = RunTelemetry(run_id="run-contract", started_at=RunTelemetry.now())
    with pytest.raises(PipelineError, match="without property data"):
        pipeline._underwrite(make_lead(), telemetry)


def test_cli_reports_failed_stages_and_exits_non_zero(monkeypatch, tmp_path, capsys):
    def raising_pipeline(data_dir, config, source_name="quantum_hunter"):
        return build(
            InMemoryLeadSource([make_lead(contacts=(make_contact(),))], name="stub"),
            skip_trace=RaisingSkipTrace(TimeoutError("skip trace socket timeout")),
        )

    monkeypatch.setattr(cli, "build_pipeline", raising_pipeline)
    exit_code = cli.main(["run", "--out-dir", str(tmp_path / "artifacts")])
    assert exit_code == 1
    assert "FAILED at enriched: unhandled TimeoutError" in capsys.readouterr().out


def test_cli_reports_unwritable_artifact_directory(monkeypatch, tmp_path, capsys):
    def raising_write(result, out_dir):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(cli, "write_artifacts", raising_write)
    exit_code = cli.main(["run", "--as-of", AS_OF.isoformat(), "--out-dir", str(tmp_path)])
    assert exit_code == 3
    assert "ARTIFACTS INCOMPLETE" in capsys.readouterr().out


def test_bad_as_of_is_a_client_error():
    with pytest.raises(service.ServiceError, match="ISO date"):
        service.config_from_environment({"as_of": "09-08-2026"})


def test_publish_reports_unwritable_output_as_server_error(monkeypatch, tmp_path):
    runtime = service.Runtime(data_dir=DATA_DIR, out_dir=tmp_path / "out")
    run_id = runtime.handle("POST", "/run", {"as_of": AS_OF.isoformat()}).body["run_id"]

    def raising_dashboard(result, path):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(service, "write_dashboard", raising_dashboard)
    response = runtime.handle("POST", "/publish", {"run_id": run_id})
    assert response.status == 500
    assert response.body["halt"] is True
    assert "could not write artifacts" in response.body["error"]


@pytest.fixture
def failing_server(tmp_path, monkeypatch):
    def boom(self, payload):
        raise RuntimeError("state store unreachable")

    monkeypatch.setattr(service.Runtime, "run", boom)
    runtime = service.Runtime(data_dir=DATA_DIR, out_dir=tmp_path / "out")
    server = ThreadingHTTPServer(("127.0.0.1", 0), service._make_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_unexpected_server_error_answers_with_json_500(failing_server):
    request = urllib.request.Request(
        f"{failing_server}/run",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    body = json.loads(excinfo.value.read())
    assert excinfo.value.code == 500
    assert body["halt"] is True
    assert "state store unreachable" in body["error"]
