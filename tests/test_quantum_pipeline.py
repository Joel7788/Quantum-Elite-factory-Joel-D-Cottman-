import inspect
import runpy

from conftest import DATA_DIR, PIPELINE_PATH

NO_WRITE_ARGV = ["run", "--no-artifacts", "--data-dir", str(DATA_DIR)]


def test_pipeline_module_exposes_init(pipeline):
    assert callable(pipeline.quantum_pipeline_init)


def test_init_returns_success_exit_code(pipeline):
    assert pipeline.quantum_pipeline_init(NO_WRITE_ARGV) == 0


def test_init_is_idempotent(pipeline):
    assert pipeline.quantum_pipeline_init(NO_WRITE_ARGV) == pipeline.quantum_pipeline_init(
        NO_WRITE_ARGV
    )


def test_init_reports_operator_and_analysis(pipeline, capsys):
    pipeline.quantum_pipeline_init(NO_WRITE_ARGV)
    out = capsys.readouterr().out
    assert "CONTACT PORT SUCCESSFUL" in out
    assert "Joel D Cottman" in out
    assert "Predictive Analysis" in out
    assert "SYSTEM FULLY AUTONOMOUS" in out


def test_init_defaults_to_the_run_command(pipeline):
    default = inspect.signature(pipeline.quantum_pipeline_init).parameters["argv"].default
    assert tuple(default) == ("run",)


def test_running_as_script_executes_the_real_pipeline(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["pipeline", *NO_WRITE_ARGV])
    try:
        runpy.run_path(str(PIPELINE_PATH), run_name="__main__")
    except SystemExit as exit_status:
        assert exit_status.code == 0
    out = capsys.readouterr().out
    assert "CONTACT PORT SUCCESSFUL" in out
    assert "HEALTH NOMINAL" in out


def test_importing_module_does_not_execute_init(capsys):
    runpy.run_path(str(PIPELINE_PATH), run_name="quantum_pipeline_imported")
    assert capsys.readouterr().out == ""
