#!/usr/bin/env bash
# Quantum Elite Wholesaling - build and push the Cloud Run runtime image.
# Operator: JOEL D COTTMAN
#
# Builds Dockerfile with Cloud Build and pushes it to Artifact Registry, then
# prints the pipeline_image value for terraform.tfvars.
#
#   ./scripts/publish_image.sh --project-id quantum-elite-prod
#
set -euo pipefail

PROJECT_ID=""
REGION="us-east4"
REPO_NAME="quantum-elite"
IMAGE_NAME="pipeline"
TAG="$(date -u +%Y%m%d%H%M%S)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --repo) REPO_NAME="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "error: --project-id is required" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

gcloud services enable cloudbuild.googleapis.com --project="$PROJECT_ID"
gcloud builds submit --project="$PROJECT_ID" --tag="$IMAGE" .

cat <<EOF

Pushed ${IMAGE}

Set this in terraform.tfvars:
  pipeline_image = "${IMAGE}"
EOF
