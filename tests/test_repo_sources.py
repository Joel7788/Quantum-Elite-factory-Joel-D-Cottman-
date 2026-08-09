import pytest

from conftest import REPO_ROOT

PY_FILES = sorted(p for p in REPO_ROOT.glob("*.py"))
HUNTOR_TF = REPO_ROOT / "Quantum_Huntor.tf"


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_top_level_py_files_are_valid_python(path):
    compile(path.read_text(), str(path), "exec")


def test_expected_python_files_present():
    assert "quantum elite wholesaleing pipeline.py" in {p.name for p in PY_FILES}


def test_huntor_config_is_terraform_not_python():
    assert HUNTOR_TF.is_file()
    assert not (REPO_ROOT / "Quantum_Huntor.py").exists()
    assert 'resource "quantum_system" "base44_core"' in HUNTOR_TF.read_text()


def test_ci_pipeline_steps_reference_existing_files():
    workflow = (REPO_ROOT / ".github/workflows/main.yml").read_text()
    for name in ("quantum elite wholesaleing pipeline.py", "Quantum_Huntor.tf"):
        assert name in workflow
    for stale in ("Quantum_Hunter.py", "quantum elite whol.py"):
        assert stale not in workflow
