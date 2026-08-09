#!/usr/bin/env bash
# Quantum Elite Wholesaling - GCP project bootstrap.
# Operator: JOEL D COTTMAN
#
# Creates everything Terraform needs before its first apply: the project, the
# Terraform state bucket, the Artifact Registry repository, and a deploy service
# account. Idempotent - re-running skips whatever already exists.
#
# Requires: gcloud (authenticated as a user with project + billing permissions).
#
#   ./scripts/bootstrap_gcp.sh \
#       --project-id quantum-elite-prod \
#       --billing-account 0X0X0X-0X0X0X-0X0X0X
#
set -euo pipefail

PROJECT_ID=""
BILLING_ACCOUNT=""
REGION="us-east4"
ORG_ID=""
FOLDER_ID=""
STATE_BUCKET=""
REPO_NAME="quantum-elite"
DEPLOYER_SA="quantum-elite-deployer"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --project-id ID         GCP project to create or reuse (required)
  --billing-account ID    Billing account to link (required for a new project)
  --region REGION         Region for Artifact Registry and the state bucket
                          (default: us-east4)
  --org-id ID             Create the project under this organization
  --folder-id ID          Create the project under this folder
  --state-bucket NAME     Terraform state bucket (default: <project-id>-tfstate)
  -h, --help              Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --billing-account) BILLING_ACCOUNT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --org-id) ORG_ID="$2"; shift 2 ;;
    --folder-id) FOLDER_ID="$2"; shift 2 ;;
    --state-bucket) STATE_BUCKET="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "error: --project-id is required" >&2
  exit 2
fi
if ! command -v gcloud >/dev/null 2>&1; then
  echo "error: gcloud is not installed or not on PATH" >&2
  exit 2
fi
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  echo "error: no active gcloud credentials; run 'gcloud auth login' first" >&2
  exit 2
fi

STATE_BUCKET="${STATE_BUCKET:-${PROJECT_ID}-tfstate}"
DEPLOYER_EMAIL="${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

step() { printf '\n==> %s\n' "$1"; }

step "Project ${PROJECT_ID}"
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  echo "already exists; reusing"
else
  create_args=(--name="Quantum Elite Factory")
  [[ -n "$ORG_ID" ]] && create_args+=(--organization="$ORG_ID")
  [[ -n "$FOLDER_ID" ]] && create_args+=(--folder="$FOLDER_ID")
  gcloud projects create "$PROJECT_ID" "${create_args[@]}"
fi

step "Billing"
if gcloud beta billing projects describe "$PROJECT_ID" \
    --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  echo "already linked"
elif [[ -n "$BILLING_ACCOUNT" ]]; then
  gcloud beta billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
else
  echo "WARNING: billing is not enabled and --billing-account was not given."
  echo "Every service below will fail until billing is linked."
fi

step "Enabling APIs"
# Terraform enables the pipeline's own APIs; these are the ones needed to reach
# that point (Terraform state, image hosting, and the deploy identity).
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  iam.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  --project="$PROJECT_ID"

step "Terraform state bucket gs://${STATE_BUCKET}"
if gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  echo "already exists; reusing"
else
  gcloud storage buckets create "gs://${STATE_BUCKET}" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention
  # State files hold resource metadata; versioning makes a bad apply recoverable.
  gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning
fi

step "Artifact Registry ${REPO_NAME}"
if gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "already exists; reusing"
else
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="Quantum Elite pipeline runtime images"
fi

step "Deploy service account ${DEPLOYER_EMAIL}"
if gcloud iam service-accounts describe "$DEPLOYER_EMAIL" \
    --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "already exists; reusing"
else
  gcloud iam service-accounts create "$DEPLOYER_SA" \
    --project="$PROJECT_ID" \
    --display-name="Quantum Elite Terraform deployer"
fi

# Scoped to what Quantum_Huntor.tf actually creates - no project owner/editor.
for role in \
  roles/run.admin \
  roles/workflows.admin \
  roles/cloudscheduler.admin \
  roles/datastore.owner \
  roles/secretmanager.admin \
  roles/storage.admin \
  roles/artifactregistry.writer \
  roles/iam.serviceAccountAdmin \
  roles/iam.serviceAccountUser \
  roles/resourcemanager.projectIamAdmin \
  roles/serviceusage.serviceUsageAdmin
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet >/dev/null
  echo "granted ${role}"
done

cat <<EOF

Bootstrap complete.

  project        ${PROJECT_ID}
  region         ${REGION}
  state bucket   gs://${STATE_BUCKET}
  image repo     ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}
  deployer       ${DEPLOYER_EMAIL}

Next:
  1. cp terraform.tfvars.example terraform.tfvars   # set project_id, pipeline_image
  2. ./scripts/publish_image.sh --project-id ${PROJECT_ID} --region ${REGION}
  3. terraform init -backend-config="bucket=${STATE_BUCKET}"
  4. terraform plan -var-file=terraform.tfvars

Prefer impersonation over downloading a key:
  gcloud config set auth/impersonate_service_account ${DEPLOYER_EMAIL}
EOF
