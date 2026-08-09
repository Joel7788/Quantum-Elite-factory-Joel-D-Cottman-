# QUANTUM ELITE WHOLESALING - PIPELINE RUNTIME IMAGE
# OPERATOR: JOEL D COTTMAN
#
# Build and push to Artifact Registry, then set the Terraform variable:
#   docker build -t $REGION-docker.pkg.dev/$PROJECT/quantum-elite/pipeline:latest .
#   terraform apply -var project_id=$PROJECT -var pipeline_image=<pushed tag>
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    QE_OUT_DIR=/tmp/quantum-elite

WORKDIR /app

# The runtime is stdlib-only; data fixtures ship with the image so the pipeline
# runs even before live provider credentials are wired into Secret Manager.
COPY quantum_elite ./quantum_elite
COPY data ./data

RUN useradd --create-home --uid 10001 quantum && chown -R quantum:quantum /app
USER quantum

EXPOSE 8080

CMD ["python", "-m", "quantum_elite.service"]
