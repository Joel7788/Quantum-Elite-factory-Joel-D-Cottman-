"""HTTP runtime for Cloud Run.

Cloud Workflows drives three endpoints:

``GET  /healthz``    liveness probe.
``POST /run``        executes the acquisition-to-disposition pipeline.
``POST /publish``    writes documents + telemetry dashboard for a finished run.

Routing logic lives in :func:`handle` so it is testable without a socket, and
the server itself is stdlib-only so the container needs no extra wheels.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from . import documents as docs
from .cli import build_pipeline, summarize
from .dashboard import write_dashboard
from .pipeline import PipelineConfig, PipelineResult
from .providers import ProviderError

DEFAULT_DATA_DIR = Path(os.environ.get("QE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DEFAULT_OUT_DIR = Path(os.environ.get("QE_OUT_DIR", "/tmp/quantum-elite"))


class ServiceError(Exception):
    """Raised for a request the caller must fix (mapped to 4xx)."""


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, Any]


def _decimal_env(name: str, fallback: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    try:
        return Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by config review
        raise ServiceError(f"{name} is not a valid decimal: {raw!r}") from exc


def config_from_environment(payload: Mapping[str, Any]) -> PipelineConfig:
    defaults = PipelineConfig()
    as_of = payload.get("as_of")
    return PipelineConfig(
        min_motivation_score=_decimal_env("QE_MIN_MOTIVATION_SCORE", defaults.min_motivation_score),
        assignment_fee=_decimal_env("QE_ASSIGNMENT_FEE", defaults.assignment_fee),
        as_of=date.fromisoformat(as_of) if as_of else defaults.as_of,
    )


class Runtime:
    """Holds finished runs so ``/publish`` can act on ``/run`` output."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR, out_dir: Path = DEFAULT_OUT_DIR) -> None:
        self.data_dir = data_dir
        self.out_dir = out_dir
        self._runs: dict[str, PipelineResult] = {}

    def run(self, payload: Mapping[str, Any]) -> Response:
        config = config_from_environment(payload)
        try:
            result = build_pipeline(self.data_dir, config).run()
        except ProviderError as exc:
            return Response(502, {"status": "failed", "error": str(exc)})

        self._runs[result.telemetry.run_id] = result
        telemetry = result.telemetry
        failures = telemetry.failures()
        return Response(
            200,
            {
                "status": "degraded" if failures else "ok",
                "halt": bool(failures),
                "run_id": telemetry.run_id,
                "health": telemetry.health,
                "duration_seconds": float(telemetry.duration_seconds),
                "ingested": len(result.packets),
                "under_contract": len(result.contracted),
                "assigned": len(result.assigned),
                "rejected": len(result.rejected),
                "projected_revenue": str(result.projected_revenue),
                "summary": summarize(result),
            },
        )

    def publish(self, payload: Mapping[str, Any]) -> Response:
        run_id = payload.get("run_id")
        if not run_id:
            raise ServiceError("run_id is required")
        result = self._runs.get(str(run_id))
        if result is None:
            raise ServiceError(f"unknown run_id: {run_id}")

        target = self.out_dir / str(run_id)
        written = [write_dashboard(result, target / "telemetry.html")]
        for packet in result.packets:
            if packet.documents:
                written.extend(
                    docs.write_documents(
                        packet.documents, target / "documents", packet.lead.lead_id
                    )
                )
        return Response(
            200,
            {
                "status": "ok",
                "halt": False,
                "run_id": str(run_id),
                "artifact_bucket": payload.get("artifact_bucket"),
                "artifacts": [str(path) for path in written],
            },
        )

    def handle(self, method: str, path: str, payload: Mapping[str, Any]) -> Response:
        route = (method.upper(), path.rstrip("/") or "/")
        if route == ("GET", "/healthz"):
            return Response(200, {"status": "ok", "operator": "JOEL D COTTMAN"})
        if route == ("POST", "/run"):
            return self.run(payload)
        if route == ("POST", "/publish"):
            return self.publish(payload)
        raise ServiceError(f"no route for {method.upper()} {path}")


def handle(method: str, path: str, payload: Mapping[str, Any] | None = None) -> Response:
    return Runtime().handle(method, path, payload or {})


def _make_handler(runtime: Runtime) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "QuantumElite/1.0"

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw) if raw else {}
                if not isinstance(payload, dict):
                    raise ServiceError("request body must be a JSON object")
                response = runtime.handle(method, self.path.split("?", 1)[0], payload)
            except json.JSONDecodeError as exc:
                response = Response(400, {"status": "failed", "error": f"invalid JSON: {exc}"})
            except ServiceError as exc:
                response = Response(400, {"status": "failed", "error": str(exc)})
            body = json.dumps(response.body).encode()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            self._dispatch("POST")

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[quantum-elite] {fmt % args}")

    return Handler


def serve(port: int | None = None) -> None:  # pragma: no cover - process entrypoint
    port = port or int(os.environ.get("PORT", "8080"))
    runtime = Runtime()
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(runtime))
    print(f"quantum elite runtime listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    serve()
