#!/usr/bin/env bash
# End-to-end smoke test for the local Compose stack.
# Uses a per-invocation project name so parallel/CI runs do not collide.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PROJECT="expense_dev_smoke_$$"
# Bind on a non-default host port so smoke can run alongside `make up` (which
# holds :8080). Callers can pin via HOST_PORT= or SMOKE_BASE_URL=.
export API_HOST_PORT="${HOST_PORT:-18080}"
BASE_URL="${SMOKE_BASE_URL:-http://localhost:${API_HOST_PORT}}"
WAIT_TIMEOUT="${SMOKE_WAIT_TIMEOUT:-90}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "smoke: missing required tool: $1" >&2; exit 2; }
}
need docker
need curl
need jq

if [ ! -f envs/expense.env ]; then
  echo "smoke: envs/expense.env not found." >&2
  echo "       Run: cp envs/expense.env.example envs/expense.env" >&2
  exit 2
fi
if [ ! -s secrets/pg_password.txt ]; then
  echo "smoke: secrets/pg_password.txt is missing or empty." >&2
  echo "       Run: printf 'expense-dev-password' > secrets/pg_password.txt" >&2
  exit 2
fi

# Base compose only. compose.override.yaml auto-merges into `docker compose`
# invocations by default, and its JDWP :5005 binding collides with any dev
# stack that is already running. Passing -f explicitly opts out of the merge.
COMPOSE=(docker compose -p "$PROJECT" --env-file envs/expense.env -f compose.yaml)

cleanup() {
  local rc=$?
  echo
  echo "smoke: final container state --------------------------------------"
  "${COMPOSE[@]}" ps || true
  if [ "$rc" -ne 0 ]; then
    echo "smoke: logs on failure --------------------------------------------"
    "${COMPOSE[@]}" logs --no-color --tail 200 || true
  fi
  echo "smoke: tearing down project $PROJECT"
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$rc"
}
trap cleanup EXIT

echo "smoke: project=$PROJECT base_url=$BASE_URL"

echo "smoke: bringing stack up (--wait --wait-timeout $WAIT_TIMEOUT)"
"${COMPOSE[@]}" up -d --wait --wait-timeout "$WAIT_TIMEOUT"

echo "smoke: verifying every service is healthy per docker compose ps"
ps_json=$("${COMPOSE[@]}" ps --format json)
# `docker compose ps --format json` emits one JSON object per service (JSON-Lines
# in recent versions, a single array in older ones). Normalise both to a stream.
if printf '%s\n' "$ps_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
  services_json=$(printf '%s\n' "$ps_json" | jq -c '.[]')
else
  services_json="$ps_json"
fi

unhealthy=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  name=$(printf '%s' "$line" | jq -r '.Name // .Service // "unknown"')
  health=$(printf '%s' "$line" | jq -r '.Health // ""')
  state=$(printf '%s' "$line" | jq -r '.State // ""')
  if [ "$health" != "healthy" ]; then
    # Services without a healthcheck report empty Health; require running state.
    if [ -z "$health" ] && [ "$state" = "running" ]; then
      echo "  ok  $name (running, no healthcheck)"
      continue
    fi
    echo "  BAD $name state=$state health=$health"
    unhealthy=$((unhealthy + 1))
  else
    echo "  ok  $name (healthy)"
  fi
done <<< "$services_json"

if [ "$unhealthy" -ne 0 ]; then
  echo "smoke: $unhealthy service(s) not healthy" >&2
  exit 1
fi

check_json_up() {
  local path="$1"
  local url="$BASE_URL$path"
  echo "smoke: GET $url  (expect status UP)"
  local body
  body=$(curl -fsS --max-time 10 "$url")
  local status
  status=$(printf '%s' "$body" | jq -r '.status // empty')
  if [ "$status" != "UP" ]; then
    echo "smoke: $path returned status='$status' body=$body" >&2
    return 1
  fi
}

check_http_200_or_404() {
  local path="$1"
  local url="$BASE_URL$path"
  echo "smoke: GET $url  (expect 200 or 404; 401 also accepted from a secured API)"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url")
  case "$code" in
    # 200 = found, 404 = routed-and-missing. 401 is also accepted because the
    # expense-api /api/** paths are JWT-protected: a 401 still confirms the
    # container is up, the route is wired, and security filters are running.
    # Anything else (5xx, connection refused, gateway errors) is a failure.
    200|401|404) echo "  ok  $path -> HTTP $code" ;;
    *) echo "smoke: $path returned HTTP $code (expected 200, 401, or 404)" >&2; return 1 ;;
  esac
}

check_json_up /actuator/health/readiness
check_http_200_or_404 /api/v1/merchants/mer_synth_001
check_json_up /actuator/health/liveness

echo "smoke: all checks passed"
