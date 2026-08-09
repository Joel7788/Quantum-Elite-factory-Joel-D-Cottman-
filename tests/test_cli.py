import json
import subprocess
import sys
from datetime import date
from decimal import Decimal

import pytest
from conftest import AS_OF, DATA_DIR, REPO_ROOT

from quantum_elite import cli


def run_cli(capsys, *args, out_dir=None):
    argv = ["run", "--data-dir", str(DATA_DIR), "--as-of", AS_OF.isoformat(), *args]
    if out_dir is not None:
        argv += ["--out-dir", str(out_dir)]
    code = cli.main(argv)
    return code, capsys.readouterr().out


def test_parser_defaults():
    args = cli.build_parser().parse_args(["run"])
    assert args.data_dir == cli.DATA_DIR
    assert args.out_dir == cli.DEFAULT_OUT_DIR
    assert args.as_of == cli.DEMO_AS_OF
    assert args.min_score == Decimal("0.25")
    assert args.no_artifacts is False


def test_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_parser_accepts_overrides():
    args = cli.build_parser().parse_args(
        ["run", "--min-score", "0.5", "--assignment-fee", "15000", "--as-of", "2026-01-02"]
    )
    assert args.min_score == Decimal("0.5")
    assert args.assignment_fee == Decimal("15000")
    assert args.as_of == date(2026, 1, 2)


def test_run_succeeds_and_prints_summary(capsys):
    code, out = run_cli(capsys, "--no-artifacts")
    assert code == 0
    assert cli.BANNER in out
    assert "HEALTH NOMINAL" in out
    assert "ingested       : 4" in out
    assert "projected fees : $10,000.00" in out
    assert "ASSIGNED to Harborline Capital" in out
    assert "REJECTED" in out
    assert "UNDER CONTRACT" in out


def test_no_artifacts_writes_nothing(capsys, tmp_path):
    code, out = run_cli(capsys, "--no-artifacts", out_dir=tmp_path / "artifacts")
    assert code == 0
    assert "wrote" not in out
    assert not (tmp_path / "artifacts").exists()


def test_run_writes_dashboard_and_documents(capsys, tmp_path):
    out_dir = tmp_path / "artifacts"
    code, out = run_cli(capsys, out_dir=out_dir)
    assert code == 0
    assert (out_dir / "telemetry.html").is_file()
    contracts = sorted(p.name for p in (out_dir / "documents" / "QE-1001").iterdir())
    assert contracts == [
        "assignment_agreement.txt",
        "closing_package.txt",
        "inspection_addendum.txt",
        "purchase_agreement.txt",
    ]
    assert "Joel Cottman-Boyer" in (
        out_dir / "documents" / "QE-1001" / "assignment_agreement.txt"
    ).read_text()
    assert "wrote" in out


def test_raised_min_score_rejects_every_lead(capsys):
    code, out = run_cli(capsys, "--no-artifacts", "--min-score", "0.99")
    assert code == 0
    assert "assigned       : 0" in out
    assert "projected fees : $0.00" in out


def test_provider_error_halts_with_exit_code_two(capsys, tmp_path):
    code = cli.main(["run", "--data-dir", str(tmp_path), "--no-artifacts"])
    out = capsys.readouterr().out
    assert code == 2
    assert "PIPELINE HALTED" in out


def test_build_pipeline_names_the_lead_source(tmp_path):
    (tmp_path / "leads.json").write_text(json.dumps([]))
    for name in ("properties.json", "skip_trace.json", "buyers.json"):
        (tmp_path / name).write_text("[]")
    pipeline = cli.build_pipeline(tmp_path, cli.PipelineConfig(as_of=AS_OF))
    assert pipeline.lead_source.name == "quantum_hunter"
    assert pipeline.run().packets == []


def test_legacy_entrypoint_runs_the_real_pipeline(pipeline, capsys):
    code = pipeline.quantum_pipeline_init(["run", "--no-artifacts", "--data-dir", str(DATA_DIR)])
    out = capsys.readouterr().out
    assert code == 0
    assert "CONTACT PORT SUCCESSFUL" in out
    assert "SYSTEM FULLY AUTONOMOUS" in out
    assert "HEALTH NOMINAL" in out


def test_package_is_runnable_as_a_module(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantum_elite",
            "run",
            "--data-dir",
            str(DATA_DIR),
            "--out-dir",
            str(tmp_path),
            "--as-of",
            AS_OF.isoformat(),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "HEALTH NOMINAL" in result.stdout
    assert (tmp_path / "telemetry.html").is_file()
