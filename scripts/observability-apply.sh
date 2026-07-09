#!/usr/bin/env bash
# W5D5 — apply the observability stack for expense-api.
# Regenerates the Sloth PrometheusRule, validates it with promtool, refreshes
# the Grafana dashboard ConfigMap from .grafana/dashboards/expense-api-red.json,
# then applies ServiceMonitor / PrometheusRule / AlertmanagerConfig and patches
# the deployment with the OTel agent init container.
#
# This script does NOT install kube-prometheus-stack / Loki / Tempo / OTel
# Collector — it assumes those CRDs are already present in the cluster and
# fails loudly if they are missing.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EXPENSE_NS="${EXPENSE_NS:-expense-dev}"
MON_NS="${MON_NS:-monitoring}"
DEPLOYMENT="${DEPLOYMENT:-expense-api}"
SLOTH_IMAGE="${SLOTH_IMAGE:-ghcr.io/slok/sloth:v0.11.0}"
PROM_IMAGE="${PROM_IMAGE:-prom/prometheus:v2.54.0}"
YQ_IMAGE="${YQ_IMAGE:-mikefarah/yq:4}"
DASHBOARD_JSON=".grafana/dashboards/expense-api-red.json"
PROM_RULE_MANIFEST="manifests/observability/expense-api-prometheusrule.yaml"
SLOTH_INPUT="slo/expense-api.sloth.yaml"

echo "== W5D5 observability-apply =="
echo "EXPENSE_NS=${EXPENSE_NS}  MON_NS=${MON_NS}  DEPLOYMENT=${DEPLOYMENT}"
echo

if ! command -v kubectl >/dev/null 2>&1; then
  echo "[apply] kubectl is required." >&2
  exit 2
fi

if ! kubectl get ns "${EXPENSE_NS}" >/dev/null 2>&1; then
  echo "[apply] namespace ${EXPENSE_NS} not found. Create it (or your expense stack) first." >&2
  exit 3
fi

if ! kubectl get ns "${MON_NS}" >/dev/null 2>&1; then
  echo "[apply] monitoring namespace ${MON_NS} not found." >&2
  echo "        Install kube-prometheus-stack:" >&2
  echo "        helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n ${MON_NS} --create-namespace" >&2
  exit 4
fi

echo "[1/8] Verifying operator CRDs"
for crd in servicemonitors.monitoring.coreos.com prometheusrules.monitoring.coreos.com alertmanagerconfigs.monitoring.coreos.com; do
  if ! kubectl get crd "${crd}" >/dev/null 2>&1; then
    echo "[apply] Required CRD ${crd} is missing. Install kube-prometheus-stack first." >&2
    exit 5
  fi
done

echo "[2/8] Regenerating Sloth PrometheusRule from ${SLOTH_INPUT}"
GENERATED_TMP="sloth-out/expense-api-prometheusrule.yaml"
mkdir -p sloth-out
docker run --rm -v "$PWD:/work" -w /work "${SLOTH_IMAGE}" \
  generate -i "${SLOTH_INPUT}" -o "${GENERATED_TMP}"
if ! diff -u "${PROM_RULE_MANIFEST}" "${GENERATED_TMP}"; then
  echo "[apply] Sloth output drifted from ${PROM_RULE_MANIFEST}." >&2
  echo "        Re-run: docker run --rm -v \"\$PWD:/work\" -w /work ${SLOTH_IMAGE} generate -i ${SLOTH_INPUT} -o ${PROM_RULE_MANIFEST}" >&2
  exit 6
fi

echo "[3/8] promtool check rules (via yq → raw groups)"
docker run --rm -v "$PWD:/work" -w /work "${YQ_IMAGE}" \
  eval '.spec' "${PROM_RULE_MANIFEST}" > sloth-out/rules-only.yaml
docker run --rm -v "$PWD:/work" -w /work --entrypoint promtool "${PROM_IMAGE}" \
  check rules sloth-out/rules-only.yaml

echo "[4/8] Refreshing Grafana dashboard ConfigMap from ${DASHBOARD_JSON}"
kubectl create configmap expense-api-red-dashboard \
  --namespace "${MON_NS}" \
  --from-file=expense-api-red.json="${DASHBOARD_JSON}" \
  --dry-run=client -o yaml \
  | kubectl label --local -f - \
      grafana_dashboard=1 \
      app.kubernetes.io/name=expense-api \
      app.kubernetes.io/part-of=expense \
      -o yaml --overwrite \
  | kubectl apply -f -

echo "[5/8] Applying ServiceMonitor"
kubectl apply -f manifests/observability/expense-api-servicemonitor.yaml

echo "[6/8] Applying PrometheusRule"
kubectl apply -f "${PROM_RULE_MANIFEST}"

echo "[7/8] Applying AlertmanagerConfig"
kubectl apply -f manifests/observability/expense-api-alertmanagerconfig.yaml

echo "[8/8] Patching deployment with OTel agent init container"
kubectl patch deployment "${DEPLOYMENT}" \
  --namespace "${EXPENSE_NS}" \
  --patch-file manifests/observability/expense-api-deployment-patch.yaml

echo
echo "Waiting for rollout of deployment/${DEPLOYMENT} in ${EXPENSE_NS}"
kubectl rollout status "deployment/${DEPLOYMENT}" -n "${EXPENSE_NS}" --timeout=180s

echo
echo "== observability-apply done =="
echo "Next: ./scripts/observability-smoke.sh"
