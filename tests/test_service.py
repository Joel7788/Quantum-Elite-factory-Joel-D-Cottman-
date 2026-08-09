import json
import threading
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer

import pytest
from conftest import AS_OF, DATA_DIR

from quantum_elite import service


@pytest.fixture
def runtime(tmp_path):
    return service.Runtime(data_dir=DATA_DIR, out_dir=tmp_path / "out")


def test_healthz(runtime):
    response = runtime.handle("GET", "/healthz", {})
    assert response.status == 200
    assert response.body == {"status": "ok", "operator": "JOEL D COTTMAN"}


def test_unknown_route_is_a_client_error(runtime):
    with pytest.raises(service.ServiceError, match="no route"):
        runtime.handle("POST", "/nope", {})


def test_run_returns_rollups_the_workflow_gates_on(runtime):
    response = runtime.handle("POST", "/run", {"as_of": AS_OF.isoformat()})
    body = response.body
    assert response.status == 200
    assert body["status"] == "ok"
    assert body["halt"] is False
    assert body["health"] == "nominal"
    assert body["ingested"] == 4
    assert body["assigned"] == 1
    assert body["under_contract"] == 2
    assert body["rejected"] == 2
    assert body["projected_revenue"] == "10000.00"
    assert any("HEALTH NOMINAL" in line for line in body["summary"])
    assert json.dumps(body)  # the response must be JSON-serialisable for Workflows


def test_run_reports_provider_failure_as_bad_gateway(tmp_path):
    runtime = service.Runtime(data_dir=tmp_path / "missing", out_dir=tmp_path / "out")
    response = runtime.handle("POST", "/run", {})
    assert response.status == 502
    assert response.body["status"] == "failed"
    assert "not found" in response.body["error"]


def test_publish_writes_artifacts_for_a_finished_run(runtime, tmp_path):
    run_id = runtime.handle("POST", "/run", {"as_of": AS_OF.isoformat()}).body["run_id"]
    response = runtime.handle(
        "POST", "/publish", {"run_id": run_id, "artifact_bucket": "qe-prod-artifacts"}
    )
    assert response.status == 200
    assert response.body["artifact_bucket"] == "qe-prod-artifacts"
    artifacts = [str(path) for path in response.body["artifacts"]]
    assert any(path.endswith("telemetry.html") for path in artifacts)
    assert any(path.endswith("assignment_agreement.txt") for path in artifacts)
    assert (tmp_path / "out" / run_id / "telemetry.html").is_file()


@pytest.mark.parametrize(
    "payload, message",
    [({}, "run_id is required"), ({"run_id": "ghost"}, "unknown run_id")],
)
def test_publish_validates_run_id(runtime, payload, message):
    with pytest.raises(service.ServiceError, match=message):
        runtime.handle("POST", "/publish", payload)


def test_config_reads_tuning_from_the_environment(monkeypatch):
    monkeypatch.setenv("QE_MIN_MOTIVATION_SCORE", "0.5")
    monkeypatch.setenv("QE_ASSIGNMENT_FEE", "12500")
    config = service.config_from_environment({"as_of": "2026-01-02"})
    assert config.min_motivation_score == Decimal("0.5")
    assert config.assignment_fee == Decimal("12500")
    assert config.effective_date.isoformat() == "2026-01-02"


def test_config_falls_back_to_defaults(monkeypatch):
    monkeypatch.delenv("QE_MIN_MOTIVATION_SCORE", raising=False)
    monkeypatch.delenv("QE_ASSIGNMENT_FEE", raising=False)
    config = service.config_from_environment({})
    assert config.min_motivation_score == Decimal("0.25")
    assert config.assignment_fee == Decimal("10000")


def test_module_level_handle_uses_a_fresh_runtime():
    assert service.handle("GET", "/healthz").status == 200


@pytest.fixture
def http_server(tmp_path):
    runtime = service.Runtime(data_dir=DATA_DIR, out_dir=tmp_path / "out")
    server = ThreadingHTTPServer(("127.0.0.1", 0), service._make_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def post(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_server_serves_the_workflow_endpoints(http_server):
    with urllib.request.urlopen(f"{http_server}/healthz") as response:
        assert json.loads(response.read())["status"] == "ok"

    status, run = post(f"{http_server}/run", {"as_of": AS_OF.isoformat()})
    assert status == 200 and run["health"] == "nominal"

    status, published = post(f"{http_server}/publish", {"run_id": run["run_id"]})
    assert status == 200 and published["artifacts"]


def test_server_rejects_malformed_requests(http_server):
    request = urllib.request.Request(
        f"{http_server}/run", data=b"{not json", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 400
    assert "invalid JSON" in json.loads(excinfo.value.read())["error"]


def test_server_rejects_non_object_bodies(http_server):
    request = urllib.request.Request(
        f"{http_server}/run", data=b"[1, 2]", method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 400
    assert "JSON object" in json.loads(excinfo.value.read())["error"]


def test_server_rejects_unknown_paths(http_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{http_server}/unknown")
    assert excinfo.value.code == 400


@pytest.mark.parametrize("as_of", ["not-a-date", "2026-13-01", 20260809])
def test_invalid_as_of_is_a_client_error(runtime, as_of):
    with pytest.raises(service.ServiceError, match="as_of"):
        runtime.handle("POST", "/run", {"as_of": as_of})


def test_server_rejects_oversized_bodies(http_server):
    oversized = json.dumps({"as_of": "x" * (service.MAX_BODY_BYTES + 1)}).encode()
    request = urllib.request.Request(
        f"{http_server}/run", data=oversized, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request)
    assert excinfo.value.code == 413
