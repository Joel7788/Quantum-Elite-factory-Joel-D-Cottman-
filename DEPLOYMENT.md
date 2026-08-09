# Quantum Elite Wholesaling — GCP Deployment Runbook

Operator: JOEL D COTTMAN

`Quantum_Huntor.tf` deploys the acquisition-to-disposition pipeline onto Cloud
Run + Workflows + Firestore + Cloud Scheduler. This runbook covers everything
between an empty Google account and a scheduled autonomous run.

Terraform cannot create the project, its own state bucket, or the image it
deploys — those come first, from `scripts/bootstrap_gcp.sh`.

## 0. Prerequisites

| Requirement | Notes |
| --- | --- |
| Google Cloud account | https://console.cloud.google.com |
| Billing account | `gcloud beta billing accounts list` — required; Cloud Run, Workflows, and Firestore are not available on a project without billing |
| `gcloud` CLI | https://cloud.google.com/sdk/docs/install |
| Terraform >= 1.5 | `terraform version` |
| Project-creation rights | `roles/resourcemanager.projectCreator` on the org/folder, or use an existing project |

```bash
gcloud auth login
gcloud auth application-default login   # what Terraform's provider reads
```

## 1. Bootstrap the project

```bash
./scripts/bootstrap_gcp.sh \
  --project-id quantum-elite-prod \
  --billing-account 0X0X0X-0X0X0X-0X0X0X
```

Creates (idempotently): the project, billing link, bootstrap APIs, a versioned
Terraform state bucket, an Artifact Registry docker repo, and a
`quantum-elite-deployer` service account scoped to only the resources
`Quantum_Huntor.tf` manages — no `roles/owner` or `roles/editor`.

## 2. Build and push the runtime image

```bash
./scripts/publish_image.sh --project-id quantum-elite-prod
```

The default `pipeline_image` is Google's hello-world sample and does not serve
`/run` or `/publish`; the Workflows execution will fail against it. Use the
image digest this script prints.

## 3. Configure variables

```bash
cp terraform.tfvars.example terraform.tfvars
```

Set `project_id` and `pipeline_image`. Keep `environment = "dev"` for the first
apply — `prod` enables Cloud Run deletion protection. `terraform.tfvars` is
gitignored and must never hold secret values, only Secret Manager secret names.

## 4. Apply

```bash
terraform init -backend-config="bucket=quantum-elite-prod-tfstate"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

## 5. Populate provider secrets

Terraform creates empty Secret Manager containers; the values are added out of
band so they never enter state or version control:

```bash
printf '%s' "$ZILLOW_KEY"        | gcloud secrets versions add zillow-api-key         --data-file=- --project=quantum-elite-prod
printf '%s' "$PUBLIC_RECORDS_KEY"| gcloud secrets versions add public-records-api-key  --data-file=- --project=quantum-elite-prod
printf '%s' "$SKIP_TRACE_KEY"    | gcloud secrets versions add skip-trace-api-key      --data-file=- --project=quantum-elite-prod
```

Until real keys exist the pipeline runs against the bundled JSON fixtures in
`data/`, which is why the offline run rejects QE-1003 (no property record) and
leaves QE-1004 unmatched (no Delaware cash buyer).

## 6. Verify

```bash
terraform output
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$(terraform output -raw pipeline_service_url)/healthz"
gcloud workflows executions list "$(terraform output -raw workflow_id)" --location us-east4
```

The Cloud Run service is `INGRESS_TRAFFIC_ALL` because Workflows calls it
without VPC egress; access is gated by IAM `run.invoker` + OIDC, and there is no
`allUsers` binding.

## 7. Credential handling

Prefer impersonation over downloaded keys:

```bash
gcloud config set auth/impersonate_service_account \
  quantum-elite-deployer@quantum-elite-prod.iam.gserviceaccount.com
```

For CI, prefer Workload Identity Federation over a JSON key. If a key is
unavoidable, store it as a secret — never commit it, and rotate it on a
schedule.

## Legal

Generated purchase, assignment, addendum, and closing documents are **drafts**
carrying an attorney-review banner. Nothing is signed or executed
automatically. Have counsel review the templates before any live transaction.
