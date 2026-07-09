#!/usr/bin/env bash
# k8s-smoke.sh — end-to-end verification for the W5D3 stack.
#
# Idempotent, safe to re-run. Assumes ./scripts/k8s-up.sh (or the k8s-ci
# workflow) has already applied manifests and rolled out the Deployment.
# Gates readiness through the actual Ingress hop rather than kubectl
# port-forward, so a broken Service/Ingress path fails loudly instead of
# silently passing.
#
#   ./scripts/k8s-smoke.sh
#   HOST_PORT=8080 ./scripts/k8s-smoke.sh

set -euo pipefail

NAMESPACE="expense-dev"
HOST_PORT="${HOST_PORT:-8080}"
INGRESS_HOST="expense.dev.uptimecrew.internal"
BASE_URL="http://localhost:${HOST_PORT}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "k8s-smoke: missing required tool: $1" >&2; exit 2; }
}
need kubectl
need curl

diagnostics() {
  echo
  echo "===== kubectl get all -n ${NAMESPACE} -o wide ====="
  kubectl get all -n "$NAMESPACE" -o wide || true
  echo
  echo "===== kubectl get endpointslice -n ${NAMESPACE} -l kubernetes.io/service-name=expense-api ====="
  kubectl get endpointslice -n "$NAMESPACE" -l kubernetes.io/service-name=expense-api -o wide || true
  echo
  echo "===== kubectl get events -n ${NAMESPACE} --sort-by=.lastTimestamp ====="
  kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp || true
  echo
  echo "===== kubectl describe deploy/expense-api ====="
  kubectl describe deploy/expense-api -n "$NAMESPACE" || true
  echo
  echo "===== kubectl describe pods (expense-api) ====="
  kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/name=expense-api || true
  echo
  echo "===== kubectl logs deploy/expense-api (tail 300) ====="
  kubectl logs deploy/expense-api -n "$NAMESPACE" --tail=300 || true
}
trap 'rc=$?; if [ "$rc" -ne 0 ]; then diagnostics; fi; exit "$rc"' EXIT

# --- 1. rollout gate ----------------------------------------------------------
echo "k8s-smoke: waiting for expense-api rollout"
kubectl rollout status deploy/expense-api -n "$NAMESPACE" --timeout=5m

# --- 2. endpoint gate ---------------------------------------------------------
# The Service is Ready when at least one EndpointSlice has a ready endpoint.
# Without this gate curl can win the race and hit the Ingress while the
# controller still shows "no active endpoints", which produces a misleading
# 503 instead of the actual application readiness state.
echo "k8s-smoke: waiting for a ready endpoint in EndpointSlice"
deadline=$((SECONDS + 120))
while :; do
  ready=$(kubectl get endpointslice -n "$NAMESPACE" \
    -l kubernetes.io/service-name=expense-api \
    -o jsonpath='{range .items[*].endpoints[*]}{.conditions.ready}{"\n"}{end}' \
    2>/dev/null | grep -c "true" || true)
  if [ "$ready" -ge 1 ]; then
    echo "  ready endpoints: $ready"
    break
  fi
  if [ $SECONDS -ge $deadline ]; then
    echo "k8s-smoke: no ready endpoints after 120s" >&2
    exit 1
  fi
  sleep 3
done

# --- 3. HTTP checks through the Ingress --------------------------------------
check_json_up() {
  local path="$1"
  local url="${BASE_URL}${path}"
  echo "k8s-smoke: GET ${url}  (Host: ${INGRESS_HOST}, expect status UP)"
  local body
  body=$(curl -fsS --max-time 10 -H "Host: ${INGRESS_HOST}" "$url")
  local status
  status=$(printf '%s' "$body" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [ "$status" != "UP" ]; then
    echo "k8s-smoke: ${path} returned status='${status}' body=${body}" >&2
    return 1
  fi
}

check_http_reachable() {
  local path="$1"
  local url="${BASE_URL}${path}"
  echo "k8s-smoke: GET ${url}  (Host: ${INGRESS_HOST}, expect 200 / 404 / 401)"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "Host: ${INGRESS_HOST}" "$url")
  case "$code" in
    # 200 = found, 404 = routed-and-missing, 401 = route reachable but JWT-
    # protected (SecurityConfig secures /api/**). Anything else means the
    # request never made it to the app.
    200|401|404) echo "  ok  ${path} -> HTTP ${code}" ;;
    *) echo "k8s-smoke: ${path} returned HTTP ${code} (expected 200, 401, or 404)" >&2; return 1 ;;
  esac
}

check_json_up /actuator/health/readiness
check_http_reachable /api/v1/merchants/mer_synth_001
check_json_up /actuator/health/liveness

echo "k8s-smoke: all checks passed"
