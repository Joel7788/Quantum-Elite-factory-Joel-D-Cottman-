import runpy

from conftest import PIPELINE_PATH


def test_pipeline_module_exposes_init(pipeline):
    assert callable(pipeline.quantum_pipeline_init)


def test_init_returns_autonomous_status(pipeline):
    assert pipeline.quantum_pipeline_init() == "SYSTEM FULLY AUTONOMOUS"


def test_init_is_idempotent(pipeline):
    assert pipeline.quantum_pipeline_init() == pipeline.quantum_pipeline_init()


def test_init_reports_operator_and_analysis(pipeline, capsys):
    pipeline.quantum_pipeline_init()
    out = capsys.readouterr().out
    assert "CONTACT PORT SUCCESSFUL" in out
    assert "Joel D Cottman" in out
    assert "Predictive Analysis" in out


def test_init_takes_no_arguments(pipeline):
    import inspect

    assert inspect.signature(pipeline.quantum_pipeline_init).parameters == {}


def test_running_as_script_executes_init(capsys):
    runpy.run_path(str(PIPELINE_PATH), run_name="__main__")
    out = capsys.readouterr().out
    assert "CONTACT PORT SUCCESSFUL" in out


def test_importing_module_does_not_execute_init(capsys):
    runpy.run_path(str(PIPELINE_PATH), run_name="quantum_pipeline_imported")
    assert capsys.readouterr().out == ""
