#!/usr/bin/env bash
# Creates a GCP service account scoped to Cloud Monitoring read-only,
# then prints the JSON key you paste into Grafana Cloud.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <project-id> [region]"
  echo "  Example: $0 my-gcp-project us-central1"
  exit 1
fi

PROJECT_ID="$1"
REGION="${2:-us-central1}"
SA_NAME="grafana-reader"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY_FILE="grafana-sa-key.json"
GCLOUD="${GCLOUD_BIN:-gcloud}"

echo "[1/4] Enabling Cloud Monitoring API"
"${GCLOUD}" services enable monitoring.googleapis.com \
  --project "${PROJECT_ID}"

echo "[2/4] Creating service account ${SA_EMAIL}"
if "${GCLOUD}" iam service-accounts describe "${SA_EMAIL}" \
    --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "  Service account already exists, skipping creation."
else
  "${GCLOUD}" iam service-accounts create "${SA_NAME}" \
    --display-name "Grafana Cloud Monitoring Reader" \
    --project "${PROJECT_ID}"
fi

echo "[3/4] Granting roles/monitoring.viewer"
# Wait briefly for SA creation to propagate across GCP
sleep 5
"${GCLOUD}" projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/monitoring.viewer"

echo "[4/4] Generating key -> ${KEY_FILE}"
rm -f "${KEY_FILE}"
"${GCLOUD}" iam service-accounts keys create "${KEY_FILE}" \
  --iam-account "${SA_EMAIL}" \
  --project "${PROJECT_ID}"

echo
echo "Done. Next steps:"
echo ""
echo "1. Go to your Grafana Cloud stack:"
echo "   https://grafana.com  →  your stack  →  Connections  →  Add new connection"
echo "   Search for: Google Cloud Monitoring"
echo ""
echo "2. In the datasource config:"
echo "   Authentication type: Google JWT File"
echo "   Paste the contents of: $(pwd)/${KEY_FILE}"
echo "   Default project: ${PROJECT_ID}"
echo "   Click Save & Test"
echo ""
echo "3. Import dashboards from monitoring/grafana/dashboards/gcp-*.json"
echo "   Grafana  →  Dashboards  →  Import  →  Upload JSON file"
echo "   Set the datasource variable to the one you just created"
echo ""
echo "   Key Cloud Run metrics you'll see immediately:"
echo "   - Request rate & latency (p50/p95/p99)"
echo "   - 5xx error rate"
echo "   - Instance count (scaling events)"
echo "   - CPU / memory utilization"
echo ""
echo "IMPORTANT: delete ${KEY_FILE} after pasting it into Grafana."
echo "  rm ${KEY_FILE}"
