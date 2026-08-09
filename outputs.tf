/* QUANTUM ELITE WHOLESALING - OUTPUTS
   OPERATOR: JOEL D COTTMAN
*/

output "pipeline_service_url" {
  description = "Internal Cloud Run URL for the pipeline runtime."
  value       = google_cloud_run_v2_service.pipeline.uri
}

output "workflow_id" {
  description = "Fully qualified acquisition-to-disposition workflow ID."
  value       = google_workflows_workflow.acquisition_to_disposition.id
}

output "artifact_bucket" {
  description = "Bucket holding generated documents and telemetry dashboards."
  value       = google_storage_bucket.artifacts.name
}

output "firestore_database" {
  description = "Firestore database backing pipeline state."
  value       = google_firestore_database.pipeline.name
}

output "runner_service_account" {
  description = "Identity all pipeline stages execute as."
  value       = google_service_account.runner.email
}

output "external_api_secret_ids" {
  description = "Secret Manager IDs to populate with live API keys before first run."
  value       = [for secret in google_secret_manager_secret.external_api : secret.secret_id]
}
