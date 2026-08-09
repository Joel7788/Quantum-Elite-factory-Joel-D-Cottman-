import pytest
from conftest import REPO_ROOT

PY_FILES = sorted(
    path
    for path in REPO_ROOT.rglob("*.py")
    if ".git" not in path.parts and "artifacts" not in path.parts
)
HUNTOR_TF = REPO_ROOT / "Quantum_Huntor.tf"
WORKFLOW = REPO_ROOT / ".github/workflows/main.yml"


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_python_sources_compile(path):
    compile(path.read_text(), str(path), "exec")


def test_expected_entrypoints_are_present():
    names = {path.name for path in PY_FILES}
    assert "quantum elite wholesaleing pipeline.py" in names
    assert {"cli.py", "pipeline.py", "service.py"} <= names


def test_huntor_config_is_terraform_not_python():
    assert HUNTOR_TF.is_file()
    assert not (REPO_ROOT / "Quantum_Huntor.py").exists()
    assert 'resource "google_cloud_run_v2_service" "pipeline"' in HUNTOR_TF.read_text()


def test_terraform_and_container_definitions_exist():
    for name in ("versions.tf", "variables.tf", "outputs.tf", "Dockerfile"):
        assert (REPO_ROOT / name).is_file(), name
    assert (REPO_ROOT / "workflows/acquisition_to_disposition.yaml").is_file()


def test_ci_runs_real_files_without_masking_failures():
    workflow = WORKFLOW.read_text()
    for name in ("quantum elite wholesaleing pipeline.py", "pytest", "terraform"):
        assert name in workflow
    for stale in ("Quantum_Hunter.py", "quantum elite whol.py"):
        assert stale not in workflow
    assert "|| echo" not in workflow


def test_runtime_artifacts_are_not_committed():
    ignored = (REPO_ROOT / ".gitignore").read_text()
    assert "artifacts/" in ignored
    assert "__pycache__/" in ignored


def test_package_entrypoint_delegates_to_the_cli():
    body = (REPO_ROOT / "quantum_elite" / "__main__.py").read_text()
    assert "from .cli import main" in body
    assert "sys.exit(main())" in body
