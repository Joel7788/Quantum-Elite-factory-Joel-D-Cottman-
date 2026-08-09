import os
import re
import shutil
import subprocess

import pytest
from conftest import REPO_ROOT

SCRIPTS = (
    REPO_ROOT / "scripts/bootstrap_gcp.sh",
    REPO_ROOT / "scripts/publish_image.sh",
)
TFVARS_EXAMPLE = REPO_ROOT / "terraform.tfvars.example"
VARIABLES_TF = REPO_ROOT / "variables.tf"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_executable_and_strict(script):
    assert script.is_file()
    assert os.access(script, os.X_OK)
    body = script.read_text()
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script):
    bash = shutil.which("bash")
    assert bash, "bash is required to syntax-check the deploy scripts"
    subprocess.run([bash, "-n", str(script)], check=True)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_require_a_project_id(script):
    bash = shutil.which("bash")
    result = subprocess.run([bash, str(script)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--project-id is required" in result.stderr


def test_bootstrap_grants_least_privilege():
    body = (REPO_ROOT / "scripts/bootstrap_gcp.sh").read_text()
    for role in ("roles/run.admin", "roles/secretmanager.admin", "roles/storage.admin"):
        assert role in body
    for overbroad in ("roles/owner", "roles/editor"):
        assert overbroad not in body


def test_example_tfvars_sets_every_required_variable():
    variables = set(re.findall(r'^variable "([^"]+)"', VARIABLES_TF.read_text(), re.M))
    example = TFVARS_EXAMPLE.read_text()
    assigned = set(re.findall(r"^(\w+)\s*=", example, re.M))
    assert variables, "expected variables.tf to declare variables"
    assert "project_id" in assigned
    assert assigned <= variables, assigned - variables


def test_example_tfvars_carries_no_secret_values():
    example = TFVARS_EXAMPLE.read_text()
    # Only secret NAMES belong here; values live in Secret Manager.
    assert "zillow-api-key" in example
    for leak in ("private_key", "BEGIN PRIVATE KEY", "api_key ="):
        assert leak not in example


def test_local_tfvars_are_gitignored():
    ignored = (REPO_ROOT / ".gitignore").read_text()
    assert "terraform.tfvars" in ignored


def test_runbook_documents_the_bootstrap_order():
    runbook = (REPO_ROOT / "DEPLOYMENT.md").read_text()
    for step in (
        "scripts/bootstrap_gcp.sh",
        "scripts/publish_image.sh",
        "terraform.tfvars",
        "terraform apply",
        "gcloud secrets versions add",
    ):
        assert step in runbook
