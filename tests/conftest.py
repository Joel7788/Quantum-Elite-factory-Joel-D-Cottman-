import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_PATH = REPO_ROOT / "quantum elite wholesaleing pipeline.py"


def load_module_from_path(path, module_name):
    """Import a module from an arbitrary file path (the pipeline filename has spaces)."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def pipeline():
    return load_module_from_path(PIPELINE_PATH, "quantum_pipeline")
