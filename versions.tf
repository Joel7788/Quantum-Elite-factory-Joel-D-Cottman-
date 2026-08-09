/* QUANTUM ELITE WHOLESALING - PROVIDER AND STATE CONFIGURATION
   OPERATOR: JOEL D COTTMAN
*/

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.12"
    }
  }

  # Remote state keeps pipeline environments synchronized across endpoints.
  # Bucket is supplied at init time:
  #   terraform init -backend-config="bucket=<state-bucket>"
  backend "gcs" {
    prefix = "quantum-elite/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
