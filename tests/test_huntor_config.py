"""Structural checks on the Terraform architecture in Quantum_Huntor.tf.

These assert the wiring the pipeline depends on (identity, state store,
orchestration, no public invoker) without needing GCP credentials.
"""

import hcl2
import pytest
import yaml
from conftest import REPO_ROOT

HUNTOR_TF = REPO_ROOT / "Quantum_Huntor.tf"
VARIABLES_TF = REPO_ROOT / "variables.tf"
VERSIONS_TF = REPO_ROOT / "versions.tf"
OUTPUTS_TF = REPO_ROOT / "outputs.tf"
WORKFLOW_YAML = REPO_ROOT / "workflows" / "acquisition_to_disposition.yaml"


def unquote(value):
    """python-hcl2 keeps the source quoting on labels and string literals."""
    return value.strip('"') if isinstance(value, str) else value


def blocks(parsed, section):
    """Flatten ``[{'"type"': {'"name"': body}}, ...]`` into ``{type.name: body}``."""
    merged = {}
    for block in parsed.get(section, []):
        for raw_type, bodies in block.items():
            if raw_type.startswith("__"):
                continue
            if isinstance(bodies, dict) and any(k.startswith('"') for k in bodies):
                for raw_name, body in bodies.items():
                    merged[f"{unquote(raw_type)}.{unquote(raw_name)}"] = body
            else:
                merged[unquote(raw_type)] = bodies
    return merged


@pytest.fixture(scope="module")
def huntor():
    return blocks(hcl2.loads(HUNTOR_TF.read_text()), "resource")


@pytest.fixture(scope="module")
def locals_block():
    return hcl2.loads(HUNTOR_TF.read_text())["locals"][0]


def test_pipeline_resources_are_declared(huntor):
    assert {
        "google_service_account.runner",
        "google_project_iam_member.runner",
        "google_firestore_database.pipeline",
        "google_storage_bucket.artifacts",
        "google_secret_manager_secret.external_api",
        "google_cloud_run_v2_service.pipeline",
        "google_workflows_workflow.acquisition_to_disposition",
        "google_cloud_scheduler_job.daily_sweep",
    } <= set(huntor)


def test_required_google_apis_are_enabled(locals_block):
    services = {unquote(s) for s in locals_block["required_services"]}
    assert {
        "run.googleapis.com",
        "workflows.googleapis.com",
        "workflowexecutions.googleapis.com",
        "cloudscheduler.googleapis.com",
        "firestore.googleapis.com",
        "secretmanager.googleapis.com",
    } <= services


def test_runner_identity_holds_only_least_privilege_roles(huntor, locals_block):
    assert {unquote(role) for role in locals_block["runner_roles"]} == {
        "roles/datastore.user",
        "roles/secretmanager.secretAccessor",
        "roles/workflows.invoker",
        "roles/logging.logWriter",
    }
    iam = huntor["google_project_iam_member.runner"]
    assert "google_service_account.runner.email" in iam["member"]


def test_nothing_is_granted_to_all_users(huntor):
    members = [
        body["member"]
        for name, body in huntor.items()
        if "iam_member" in name and "member" in body
    ]
    assert members
    assert not [m for m in members if "allUsers" in m or "allAuthenticatedUsers" in m]


def test_state_store_is_firestore_native_with_recovery(huntor):
    firestore = huntor["google_firestore_database.pipeline"]
    assert unquote(firestore["type"]) == "FIRESTORE_NATIVE"
    assert (
        unquote(firestore["point_in_time_recovery_enablement"])
        == "POINT_IN_TIME_RECOVERY_ENABLED"
    )
    assert "var.firestore_location" in firestore["location_id"]


def test_artifact_bucket_is_private_versioned_and_expiring(huntor):
    bucket = huntor["google_storage_bucket.artifacts"]
    assert bucket["uniform_bucket_level_access"] is True
    assert bucket["versioning"][0]["enabled"] is True
    assert unquote(bucket["lifecycle_rule"][0]["action"][0]["type"]) == "Delete"
    assert "var.artifact_retention_days" in bucket["lifecycle_rule"][0]["condition"][0]["age"]


def test_secrets_are_created_empty_for_operator_population(huntor):
    secret = huntor["google_secret_manager_secret.external_api"]
    assert "var.external_api_secrets" in secret["for_each"]
    assert "replication" in secret
    # Terraform creates the containers only; it must never carry secret values.
    assert "secret_data" not in HUNTOR_TF.read_text()


def test_cloud_run_receives_state_and_tuning_configuration(huntor):
    template = huntor["google_cloud_run_v2_service.pipeline"]["template"][0]
    env_names = {unquote(env["name"]) for env in template["containers"][0]["env"]}
    assert {
        "QE_FIRESTORE_DATABASE",
        "QE_ARTIFACT_BUCKET",
        "QE_MIN_MOTIVATION_SCORE",
        "QE_ASSIGNMENT_FEE",
    } <= env_names
    assert "google_service_account.runner.email" in template["service_account"]


def test_workflow_is_rendered_from_the_yaml_definition(huntor):
    workflow = huntor["google_workflows_workflow.acquisition_to_disposition"]
    assert "acquisition_to_disposition.yaml" in workflow["source_contents"]
    assert "google_cloud_run_v2_service.pipeline.uri" in workflow["source_contents"]
    assert "google_storage_bucket.artifacts.name" in workflow["source_contents"]


def test_scheduler_triggers_the_workflow_with_authenticated_calls(huntor):
    job = huntor["google_cloud_scheduler_job.daily_sweep"]
    target = job["http_target"][0]
    assert unquote(target["http_method"]) == "POST"
    assert "workflowexecutions.googleapis.com" in str(target["uri"])
    assert (
        "google_service_account.runner.email"
        in target["oauth_token"][0]["service_account_email"]
    )
    assert "var.pipeline_schedule" in job["schedule"]


def test_variables_are_declared_with_descriptions():
    variables = blocks(hcl2.loads(VARIABLES_TF.read_text()), "variable")
    expected = {
        "project_id",
        "region",
        "environment",
        "pipeline_image",
        "firestore_location",
        "pipeline_schedule",
        "schedule_timezone",
        "min_motivation_score",
        "assignment_fee",
        "external_api_secrets",
        "artifact_retention_days",
        "labels",
    }
    assert expected <= set(variables)
    assert all(variables[name].get("description") for name in expected)


def test_provider_and_backend_are_pinned():
    versions = hcl2.loads(VERSIONS_TF.read_text())["terraform"][0]
    assert unquote(versions["required_version"]).startswith(">=")
    google = versions["required_providers"][0]["google"]
    assert unquote(google["source"]) == "hashicorp/google"
    assert unquote(google["version"]).startswith("~>")
    assert versions["backend"]


def test_outputs_expose_the_deployed_endpoints():
    outputs = blocks(hcl2.loads(OUTPUTS_TF.read_text()), "output")
    assert {
        "pipeline_service_url",
        "workflow_id",
        "artifact_bucket",
        "firestore_database",
        "runner_service_account",
        "external_api_secret_ids",
    } <= set(outputs)


def test_workflow_yaml_calls_the_service_endpoints_it_gates_on():
    body = WORKFLOW_YAML.read_text()
    # Terraform interpolations are single-$; workflow expressions are escaped $$.
    rendered = yaml.safe_load(
        body.replace("${pipeline_url}", "https://run.example").replace(
            "${artifact_bucket}", "qe-artifacts"
        )
    )
    steps = [name for step in rendered["main"]["steps"] for name in step]
    assert steps == [
        "init",
        "acquire_and_dispose",
        "log_run",
        "gate_on_health",
        "publish_artifacts",
        "done",
        "halted",
    ]
    assert '/run"' in body and '/publish"' in body
    assert "OIDC" in body
    assert "max_retries" in body
