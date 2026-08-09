/* QUANTUM ELITE WHOLESALING - INPUT VARIABLES
   OPERATOR: JOEL D COTTMAN
*/

variable "project_id" {
  description = "GCP project hosting the Quantum Elite pipeline."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Workflows, and Scheduler."
  type        = string
  default     = "us-east4"
}

variable "environment" {
  description = "Deployment environment; suffixes every resource name."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "pipeline_image" {
  description = "Container image running the quantum_elite pipeline CLI."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "firestore_location" {
  description = "Multi-region location for the Firestore state store."
  type        = string
  default     = "nam5"
}

variable "pipeline_schedule" {
  description = "Cron schedule for the autonomous daily acquisition sweep."
  type        = string
  default     = "0 6 * * *"
}

variable "schedule_timezone" {
  description = "Time zone the pipeline schedule is evaluated in."
  type        = string
  default     = "America/New_York"
}

variable "min_motivation_score" {
  description = "Motivation score floor below which leads are not underwritten."
  type        = number
  default     = 0.25

  validation {
    condition     = var.min_motivation_score >= 0 && var.min_motivation_score <= 1
    error_message = "min_motivation_score must be within 0-1."
  }
}

variable "assignment_fee" {
  description = "Target assignment fee, in dollars, used when underwriting."
  type        = number
  default     = 10000

  validation {
    condition     = var.assignment_fee >= 2500
    error_message = "assignment_fee must be at least 2500 to match the underwriting floor."
  }
}

variable "external_api_secrets" {
  description = "Secret Manager entries for lead, property, and skip-trace APIs."
  type        = list(string)
  default = [
    "zillow-api-key",
    "public-records-api-key",
    "skip-trace-api-key",
  ]
}

variable "artifact_retention_days" {
  description = "Days to retain generated documents and telemetry artifacts."
  type        = number
  default     = 365
}

variable "labels" {
  description = "Labels applied to every labelable resource."
  type        = map(string)
  default = {
    system   = "quantum-elite-factory"
    operator = "joel-d-cottman"
  }
}
