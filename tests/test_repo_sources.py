import pytest

from conftest import REPO_ROOT

PY_FILES = sorted(p for p in REPO_ROOT.glob("*.py"))

# Quantum_Huntor.py holds Terraform/HCL configuration, not Python, so it cannot be
# imported or unit tested until it is renamed (e.g. Quantum_Huntor.tf).
KNOWN_NON_PYTHON = {"Quantum_Huntor.py"}


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_top_level_py_files_are_valid_python(path):
    if path.name in KNOWN_NON_PYTHON:
        pytest.xfail(f"{path.name} contains HCL, not Python")
    compile(path.read_text(), str(path), "exec")


def test_expected_python_files_present():
    assert "quantum elite wholesaleing pipeline.py" in {p.name for p in PY_FILES}
