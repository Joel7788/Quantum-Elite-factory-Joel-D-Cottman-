"""Command line entrypoint: ``python -m quantum_elite run``."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from . import documents as docs
from .dashboard import write_dashboard
from .pipeline import Pipeline, PipelineConfig, PipelineResult
from .providers import (
    JsonBuyerRepository,
    JsonLeadSource,
    JsonPropertyDataProvider,
    JsonSkipTraceProvider,
    ProviderError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUT_DIR = REPO_ROOT / "artifacts"

# The bundled sample comparables are dated, so the demo pins an effective date
# to keep runs deterministic instead of aging out of the comp window.
DEMO_AS_OF = date(2026, 8, 9)

BANNER = "CONTACT PORT SUCCESSFUL | Operator: Joel D Cottman"


def build_pipeline(
    data_dir: Path, config: PipelineConfig, source_name: str = "quantum_hunter"
) -> Pipeline:
    return Pipeline(
        lead_source=JsonLeadSource(data_dir / "leads.json", name=source_name),
        property_data=JsonPropertyDataProvider(data_dir / "properties.json"),
        skip_trace=JsonSkipTraceProvider(data_dir / "skip_trace.json"),
        buyers=JsonBuyerRepository(data_dir / "buyers.json"),
        config=config,
    )


def summarize(result: PipelineResult) -> list[str]:
    telemetry = result.telemetry
    lines = [
        BANNER,
        f"RUN {telemetry.run_id} | HEALTH {telemetry.health.upper()} "
        f"| {telemetry.duration_seconds}s",
        f"  ingested       : {len(result.packets)}",
        f"  under contract : {len(result.contracted)}",
        f"  assigned       : {len(result.assigned)}",
        f"  rejected       : {len(result.rejected)}",
        f"  projected fees : ${result.projected_revenue:,.2f}",
    ]
    for packet in result.packets:
        lead = packet.lead
        if lead.rejection_reason:
            lines.append(f"  - {lead.lead_id} REJECTED: {lead.rejection_reason}")
        elif packet.assignment is not None and packet.offer is not None:
            lines.append(
                f"  - {lead.lead_id} ASSIGNED to {packet.assignment.buyer.name} "
                f"| offer ${packet.offer.amount:,.2f} "
                f"| fee ${packet.assignment.fee:,.2f} "
                f"| docs {len(packet.documents)}"
            )
        elif packet.offer is not None:
            lines.append(
                f"  - {lead.lead_id} UNDER CONTRACT at ${packet.offer.amount:,.2f} "
                f"| awaiting buyer match"
            )
    return lines


def write_artifacts(result: PipelineResult, out_dir: Path) -> list[Path]:
    written = [write_dashboard(result, out_dir / "telemetry.html")]
    for packet in result.packets:
        if packet.documents:
            written.extend(
                docs.write_documents(packet.documents, out_dir / "documents", packet.lead.lead_id)
            )
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantum_elite", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the acquisition/disposition pipeline")
    run.add_argument("--data-dir", type=Path, default=DATA_DIR)
    run.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    run.add_argument("--min-score", type=Decimal, default=PipelineConfig().min_motivation_score)
    run.add_argument("--assignment-fee", type=Decimal, default=PipelineConfig().assignment_fee)
    run.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEMO_AS_OF,
        help="effective date for comp recency and deadlines (YYYY-MM-DD)",
    )
    run.add_argument("--no-artifacts", action="store_true", help="skip writing files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PipelineConfig(
        min_motivation_score=args.min_score,
        assignment_fee=args.assignment_fee,
        as_of=args.as_of,
    )
    try:
        result = build_pipeline(args.data_dir, config).run()
    except ProviderError as exc:
        print(f"PIPELINE HALTED | provider error: {exc}")
        return 2

    for line in summarize(result):
        print(line)

    if not args.no_artifacts:
        try:
            written = write_artifacts(result, args.out_dir)
        except OSError as exc:
            print(f"ARTIFACTS INCOMPLETE | could not write under {args.out_dir}: {exc}")
            return 3
        for path in written:
            print(f"  wrote {path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path}")

    if failures := result.telemetry.failures():
        for event in failures:
            print(f"  ! {event.lead_id} FAILED at {event.stage.value}: {event.detail}")
        return 1
    return 0
