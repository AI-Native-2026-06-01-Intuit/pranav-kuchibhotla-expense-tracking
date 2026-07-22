#!/usr/bin/env bash
# k8s-up.sh — bring up the W5D3 local Kubernetes stack on k3d.
#
# Idempotent: safe to re-run. Creates the cluster if missing, imports the
# expense-api image (whatever tag you have locally), applies all manifests,
# and waits for the Deployment to roll out. On failure it prints the same
# diagnostics k8s-smoke.sh would print, so you don't have to reach for
# kubectl separately to know what broke.
#
#   ./scripts/k8s-up.sh
#   TAG=<sha> ./scripts/k8s-up.sh        # use a different local image tag
#   CLUSTER_NAME=my-cluster ./scripts/k8s-up.sh
#
# See scripts/k8s-smoke.sh for the end-to-end verification pass.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TAG="${TAG:-0.1.0}"
IMAGE="uptimecrew/expense-api:${TAG}"
CLUSTER_NAME="${CLUSTER_NAME:-expense}"
NAMESPACE="expense-dev"
HOST_PORT="${HOST_PORT:-8080}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "k8s-up: missing required tool: $1" >&2; exit 2; }
}
need k3d
need kubectl
need docker

diagnostics() {
  echo
  echo "===== kubectl get all -n ${NAMESPACE} -o wide ====="
  kubectl get all -n "$NAMESPACE" -o wide || true
  echo
  echo "===== kubectl get events -n ${NAMESPACE} --sort-by=.lastTimestamp ====="
  kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp || true
  echo
  echo "===== kubectl describe deploy/expense-api ====="
  kubectl describe deploy/expense-api -n "$NAMESPACE" || true
  echo
  echo "===== kubectl logs deploy/expense-api (tail 200) ====="
  kubectl logs deploy/expense-api -n "$NAMESPACE" --tail=200 || true
}
trap 'rc=$?; if [ "$rc" -ne 0 ]; then diagnostics; fi; exit "$rc"' EXIT

# --- 1. cluster ---------------------------------------------------------------
if k3d cluster list --output json | grep -q "\"name\": \"${CLUSTER_NAME}\""; then
  echo "k8s-up: cluster '${CLUSTER_NAME}' already exists — reusing"
else
  echo "k8s-up: creating cluster '${CLUSTER_NAME}'"
  # --disable=traefik so we can install ingress-nginx (the manifest sets
  # ingressClassName: nginx). Port map lands host :HOST_PORT on the k3d
  # LoadBalancer's :80, which the nginx controller listens on.
  k3d cluster create "$CLUSTER_NAME" \
    --servers 1 --agents 2 \
    --port "${HOST_PORT}:80@loadbalancer" \
    --k3s-arg "--disable=traefik@server:0"
fi

kubectl config use-context "k3d-${CLUSTER_NAME}" >/dev/null

# --- 2. ingress-nginx ---------------------------------------------------------
if ! kubectl get ns ingress-nginx >/dev/null 2>&1; then
  echo "k8s-up: installing ingress-nginx"
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/cloud/deploy.yaml
fi
# Wait for the admission webhook to be usable — not just for the Deployment to
# be Available. The controller creates a ValidatingWebhookConfiguration that
# points at the ingress-nginx-controller-admission Service; if we apply the
# Ingress before an admission Pod is Ready, the webhook has no endpoints and
# the apply fails with:
#   Internal error: failed calling webhook "validate.nginx.ingress.kubernetes.io":
#   no endpoints available for service "ingress-nginx-controller-admission"
# The two-step wait below (a) blocks until at least one controller Pod is
# Ready, then (b) blocks until the admission Service has a ready endpoint.
# The controller Pod is scheduled a beat after the Deployment is created, so
# a bare `kubectl wait --for=condition=Ready` races with "no matching
# resources found". Poll until at least one Pod exists, then wait on Ready.
echo "k8s-up: waiting for ingress-nginx controller Pod to exist"
deadline=$((SECONDS + 60))
while :; do
  if kubectl get pod -n ingress-nginx \
       -l app.kubernetes.io/component=controller \
       -o name 2>/dev/null | grep -q '^pod/'; then
    break
  fi
  if [ $SECONDS -ge $deadline ]; then
    echo "k8s-up: ingress-nginx controller Pod never appeared" >&2
    exit 1
  fi
  sleep 2
done
echo "k8s-up: waiting for ingress-nginx controller Pod Ready"
kubectl wait --namespace ingress-nginx \
  --for=condition=Ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=300s
echo "k8s-up: waiting for ingress-nginx admission webhook endpoints"
deadline=$((SECONDS + 120))
while :; do
  ready=$(kubectl get endpointslice -n ingress-nginx \
    -l kubernetes.io/service-name=ingress-nginx-controller-admission \
    -o jsonpath='{range .items[*].endpoints[*]}{.conditions.ready}{"\n"}{end}' \
    2>/dev/null | grep -c "true" || true)
  if [ "$ready" -ge 1 ]; then
    echo "  admission endpoints ready: $ready"
    break
  fi
  if [ $SECONDS -ge $deadline ]; then
    echo "k8s-up: ingress-nginx admission webhook never got a ready endpoint" >&2
    exit 1
  fi
  sleep 3
done

# --- 3. image import ----------------------------------------------------------
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "k8s-up: image ${IMAGE} not in local Docker; build it first (e.g. cd expense-api && docker build -t ${IMAGE} .)"
  exit 2
fi
echo "k8s-up: importing ${IMAGE} into k3d cluster '${CLUSTER_NAME}'"
k3d image import "$IMAGE" -c "$CLUSTER_NAME"

# --- 4. schema ConfigMap ------------------------------------------------------
# Postgres reads /docker-entrypoint-initdb.d/ on first init. Building the
# ConfigMap from the tracked SQL files keeps the compose stack and the k8s
# stack schema-consistent without duplicating the SQL.
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap postgres-initdb -n "$NAMESPACE" \
  --from-file=10-schema.sql=db/V1__schema.sql \
  --from-file=30-event-outbox.sql=expense-api/src/main/resources/db/migration/V3__event_outbox.sql \
  --from-file=50-orders-refunds.sql=expense-api/src/main/resources/db/migration/V5__orders_refunds.sql \
  --dry-run=client -o yaml | kubectl apply -f -

# --- 5. secret ----------------------------------------------------------------
# The checked-in Secret manifest carries a sentinel value; overwrite it before
# rollout so Postgres and the API can actually authenticate.
CI_PG_PASSWORD="${CI_PG_PASSWORD:-expense-dev-password}"
kubectl create secret generic expense-api-secrets -n "$NAMESPACE" \
  --from-literal=SPRING_DATASOURCE_PASSWORD="$CI_PG_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

# --- 6. apply manifests -------------------------------------------------------
echo "k8s-up: applying manifests/"
kubectl apply -f manifests/

# --- 7. rollout gate ----------------------------------------------------------
echo "k8s-up: waiting for expense-api rollout (up to 8m)"
kubectl rollout status deploy/expense-api -n "$NAMESPACE" --timeout=8m

# --- 8. friendly next-step ----------------------------------------------------
echo
echo "k8s-up: cluster ready. Try:"
echo "  curl -H 'Host: expense.dev.uptimecrew.internal' http://localhost:${HOST_PORT}/actuator/health/readiness"
echo "  ./scripts/k8s-smoke.sh"
