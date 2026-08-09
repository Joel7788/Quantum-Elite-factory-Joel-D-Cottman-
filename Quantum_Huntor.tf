/* QUANTUM ELITE WHOLESALING - SYSTEM FORGE
   OPERATOR: JOEL D COTTMAN

   Serverless acquisition/disposition pipeline on GCP:
   Cloud Scheduler -> Workflows -> Cloud Run (quantum_elite CLI)
   with Firestore as the state store and GCS for generated artifacts.
*/

locals {
  suffix = var.environment
  name   = "quantum-elite-${local.suffix}"

  labels = merge(var.labels, {
    environment = var.environment
    managed_by  = "terraform"
  })

  required_services = [
    "run.googleapis.com",
    "workflows.googleapis.com",
    "workflowexecutions.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
  ]

  # Least-privilege roles for the single pipeline identity.
  runner_roles = [
    "roles/datastore.user",
    "roles/secretmanager.secretAccessor",
    "roles/workflows.invoker",
    "roles/logging.logWriter",
  ]
}

resource "google_project_service" "pipeline" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

/* ---------- IDENTITY ---------- */

resource "google_service_account" "runner" {
  account_id   = "${local.name}-runner"
  display_name = "Quantum Elite pipeline runner (${var.environment})"
  description  = "Executes lead ingestion, underwriting, and disposition stages."
}

resource "google_project_iam_member" "runner" {
  for_each = toset(local.runner_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runner.email}"
}

/* ---------- STATE STORE ---------- */

resource "google_firestore_database" "pipeline" {
  project                           = var.project_id
  name                              = "${local.name}-state"
  location_id                       = var.firestore_location
  type                              = "FIRESTORE_NATIVE"
  concurrency_mode                  = "OPTIMISTIC"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state           = var.environment == "prod" ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"

  depends_on = [google_project_service.pipeline]
}

/* ---------- ARTIFACTS ---------- */

resource "google_storage_bucket" "artifacts" {
  name                        = "${local.name}-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  # Contracts and telemetry are business records; expire them on a fixed clock.
  lifecycle_rule {
    condition {
      age = var.artifact_retention_days
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "runner_artifacts" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runner.email}"
}

/* ---------- EXTERNAL API CREDENTIALS ---------- */

resource "google_secret_manager_secret" "external_api" {
  for_each = toset(var.external_api_secrets)

  secret_id = "${local.name}-${each.value}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.pipeline]
}

/* ---------- PIPELINE RUNTIME ---------- */

resource "google_cloud_run_v2_service" "pipeline" {
  name     = "${local.name}-pipeline"
  location = var.region
  labels   = local.labels

  deletion_protection = var.environment == "prod"

  # Workflows calls Cloud Run over the public endpoint (it has no VPC egress),
  # so ingress stays open while every request is gated by run.invoker IAM +
  # OIDC. No allUsers binding exists anywhere in this configuration.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runner.email
    timeout         = "900s"

    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }

    containers {
      image = var.pipeline_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "QE_FIRESTORE_DATABASE"
        value = google_firestore_database.pipeline.name
      }

      env {
        name  = "QE_ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }

      env {
        name  = "QE_MIN_MOTIVATION_SCORE"
        value = tostring(var.min_motivation_score)
      }

      env {
        name  = "QE_ASSIGNMENT_FEE"
        value = tostring(var.assignment_fee)
      }

      dynamic "env" {
        for_each = google_secret_manager_secret.external_api

        content {
          name = upper(replace("QE_${env.key}", "-", "_"))

          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_project_service.pipeline]
}

resource "google_cloud_run_v2_service_iam_member" "workflow_invoker" {
  name     = google_cloud_run_v2_service.pipeline.name
  location = google_cloud_run_v2_service.pipeline.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runner.email}"
}

/* ---------- ORCHESTRATION ---------- */

resource "google_workflows_workflow" "acquisition_to_disposition" {
  name            = "${local.name}-acquisition-to-disposition"
  region          = var.region
  description     = "Gated lead-to-assignment flow; each stage is retried independently."
  service_account = google_service_account.runner.id
  labels          = local.labels

  source_contents = templatefile("${path.module}/workflows/acquisition_to_disposition.yaml", {
    pipeline_url    = google_cloud_run_v2_service.pipeline.uri
    artifact_bucket = google_storage_bucket.artifacts.name
  })

  depends_on = [google_project_service.pipeline]
}

resource "google_cloud_scheduler_job" "daily_sweep" {
  name        = "${local.name}-daily-sweep"
  region      = var.region
  description = "Autonomous daily motivated-seller acquisition sweep."
  schedule    = var.pipeline_schedule
  time_zone   = var.schedule_timezone

  retry_config {
    retry_count          = 3
    min_backoff_duration = "30s"
    max_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri = join("", [
      "https://workflowexecutions.googleapis.com/v1/",
      google_workflows_workflow.acquisition_to_disposition.id,
      "/executions",
    ])

    oauth_token {
      service_account_email = google_service_account.runner.email
    }
  }

  depends_on = [google_project_service.pipeline]
}
