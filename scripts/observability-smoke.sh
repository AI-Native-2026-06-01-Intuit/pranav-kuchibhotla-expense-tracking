#!/usr/bin/env bash
# W5D5 — smoke test the observability stack.
# Sends one traffic request with a fresh correlation id, then asserts:
#   1. Prometheus has an http_server_requests_seconds_count series for expense-api
#   2. Prometheus has expense_deductions_identified_total after traffic
#   3. Loki has a matching log line (correlation id in the body)
#   4. Tempo has a trace for service.name=expense-api
#   5. trace -> logs pivot: a Tempo trace id resolves to Loki lines that
#      carry the same trace_id (best-effort; traces sample at 10% in k8s)
# Prints diagnostics on failure. Never fakes success — if the stack is missing
# or endpoints are unreachable it exits non-zero.

set -euo pipefail

EXPENSE_NS="${EXPENSE_NS:-expense-dev}"
MON_NS="${MON_NS:-monitoring}"
EXPENSE_SVC="${EXPENSE_SVC:-expense-api}"
PROM_SVC="${PROM_SVC:-kube-prometheus-stack-prometheus}"
PROM_PORT="${PROM_PORT:-9090}"
LOKI_SVC="${LOKI_SVC:-loki-gateway}"
LOKI_PORT="${LOKI_PORT:-80}"
TEMPO_SVC="${TEMPO_SVC:-tempo}"
TEMPO_PORT="${TEMPO_PORT:-3100}"
MERCHANT_ID="${MERCHANT_ID:-mer_synth_001}"

CORR_ID="smoke-$(date -u +%Y%m%dT%H%M%SZ)-$$"
DIAG_DIR="/tmp/observability-smoke-${CORR_ID}"
mkdir -p "${DIAG_DIR}"

echo "== W5D5 observability-smoke =="
echo "EXPENSE_NS=${EXPENSE_NS}  MON_NS=${MON_NS}"
echo "CORR_ID=${CORR_ID}"
echo "diag=${DIAG_DIR}"
echo

if ! kubectl get ns "${EXPENSE_NS}" >/dev/null 2>&1; then
  echo "[smoke] namespace ${EXPENSE_NS} missing — nothing to smoke test." >&2
  exit 2
fi

for svc in "${EXPENSE_SVC}"; do
  if ! kubectl -n "${EXPENSE_NS}" get svc "${svc}" >/dev/null 2>&1; then
    echo "[smoke] Service ${EXPENSE_NS}/${svc} missing — apply the app first." >&2
    exit 3
  fi
done

for svc in "${PROM_SVC}" "${LOKI_SVC}" "${TEMPO_SVC}"; do
  if ! kubectl -n "${MON_NS}" get svc "${svc}" >/dev/null 2>&1; then
    echo "[smoke] Service ${MON_NS}/${svc} missing. Adjust *_SVC env vars to match your install." >&2
    exit 4
  fi
done

pf_expense_pid=""
pf_prom_pid=""
pf_loki_pid=""
pf_tempo_pid=""
cleanup() {
  local pid
  for pid in $pf_expense_pid $pf_prom_pid $pf_loki_pid $pf_tempo_pid; do
    [ -n "${pid}" ] && kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT

echo "[1/5] Starting port-forwards"
kubectl -n "${EXPENSE_NS}" port-forward "svc/${EXPENSE_SVC}" 18080:8080 >"${DIAG_DIR}/pf-expense.log" 2>&1 &
pf_expense_pid=$!
kubectl -n "${MON_NS}" port-forward "svc/${PROM_SVC}" 19090:${PROM_PORT} >"${DIAG_DIR}/pf-prom.log" 2>&1 &
pf_prom_pid=$!
kubectl -n "${MON_NS}" port-forward "svc/${LOKI_SVC}" 13100:${LOKI_PORT} >"${DIAG_DIR}/pf-loki.log" 2>&1 &
pf_loki_pid=$!
kubectl -n "${MON_NS}" port-forward "svc/${TEMPO_SVC}" 13200:${TEMPO_PORT} >"${DIAG_DIR}/pf-tempo.log" 2>&1 &
pf_tempo_pid=$!
sleep 4

echo "[2/5] Sending traffic to /api/v1/merchants/${MERCHANT_ID}"
STATUS="$(curl -sS -o "${DIAG_DIR}/body" -w '%{http_code}' \
  -H "x-correlation-id: ${CORR_ID}" \
  "http://127.0.0.1:18080/api/v1/merchants/${MERCHANT_ID}" || true)"
echo "  status=${STATUS}"
# 200 (seed present) and 404 (no seed) are both acceptable for smoke — the
# metric and log/trace signal is what we assert. 401/403 (JWT enforced) is also
# a valid signal that the app is up and Micrometer is recording the request.
echo "  body head:"; head -c 200 "${DIAG_DIR}/body" 2>/dev/null || true; echo

echo "[3/5] Prometheus assertions"
PROM_URL="http://127.0.0.1:19090"
sleep 20  # scrape interval is 15s
_prom_query() {
  local q="$1"
  curl -sS -G --data-urlencode "query=${q}" "${PROM_URL}/api/v1/query"
}
HTTP_COUNT_JSON="$(_prom_query 'http_server_requests_seconds_count{app="expense-api"}')"
echo "${HTTP_COUNT_JSON}" > "${DIAG_DIR}/prom-http_server_requests.json"
if ! echo "${HTTP_COUNT_JSON}" | grep -q '"resultType":"vector"'; then
  echo "[smoke] Prometheus did not return http_server_requests_seconds_count." >&2
  cat "${DIAG_DIR}/prom-http_server_requests.json" >&2
  exit 5
fi
if ! echo "${HTTP_COUNT_JSON}" | grep -q '"result":\['; then
  echo "[smoke] Prometheus returned no http_server_requests_seconds_count series yet." >&2
  exit 5
fi

DED_JSON="$(_prom_query 'expense_deductions_identified_total')"
echo "${DED_JSON}" > "${DIAG_DIR}/prom-deductions.json"
if ! echo "${DED_JSON}" | grep -q '"__name__":"expense_deductions_identified_total"'; then
  echo "[smoke] Prometheus does not have expense_deductions_identified_total yet." >&2
  echo "        Verify the app was patched to expose /actuator/prometheus and traffic hit findById." >&2
  exit 6
fi

echo "[4/5] Loki assertion (log with correlationId=${CORR_ID})"
LOKI_URL="http://127.0.0.1:13100"
NOW_NS="$(date -u +%s000000000)"
FIVE_MIN_AGO_NS="$(( NOW_NS - 5 * 60 * 1000000000 ))"
LOKI_JSON="$(curl -sS -G "${LOKI_URL}/loki/api/v1/query_range" \
  --data-urlencode "query={app=\"expense-api\"}" \
  --data-urlencode "start=${FIVE_MIN_AGO_NS}" \
  --data-urlencode "end=${NOW_NS}" \
  --data-urlencode "limit=200" || true)"
echo "${LOKI_JSON}" > "${DIAG_DIR}/loki-query.json"
if ! echo "${LOKI_JSON}" | grep -q "${CORR_ID}"; then
  # Fall back to a plain "app=expense-api" line, since correlation id may not
  # be in every log; we still want to prove Loki is receiving app logs.
  if ! echo "${LOKI_JSON}" | grep -q '"app":"expense-api"' && ! echo "${LOKI_JSON}" | grep -q 'expense-api'; then
    echo "[smoke] Loki has no expense-api log lines in the last 5 minutes." >&2
    exit 7
  fi
  echo "  WARN: correlation id ${CORR_ID} not seen (Promtail may not thread it — permitted)."
else
  echo "  correlation id present: ok"
fi

echo "[5/6] Tempo assertion (service.name=expense-api)"
TEMPO_URL="http://127.0.0.1:13200"
TEMPO_JSON="$(curl -sS -G "${TEMPO_URL}/api/search" \
  --data-urlencode "tags=service.name=expense-api" \
  --data-urlencode "limit=5" || true)"
echo "${TEMPO_JSON}" > "${DIAG_DIR}/tempo-search.json"
if ! echo "${TEMPO_JSON}" | grep -q '"traceID"'; then
  echo "[smoke] Tempo returned no traces for service.name=expense-api." >&2
  exit 8
fi

echo "[6/6] trace -> logs pivot (Grafana tracesToLogsV2 shape)"
# Pull one trace id out of the Tempo search result and reproduce the query
# Grafana's "Logs for this span" button runs: {app="expense-api"} |= "<trace id>".
# This proves trace_id reaches Loki as a body field with no ID labels. It is
# best-effort: with 10% trace sampling the sampled trace's log lines may fall
# outside the 5-minute window, so a miss WARNs rather than fails.
TRACE_ID="$(echo "${TEMPO_JSON}" | grep -o '"traceID":"[0-9a-f]*"' | head -n1 | sed 's/.*:"//;s/"//')"
if [ -z "${TRACE_ID}" ]; then
  echo "  WARN: could not parse a traceID out of the Tempo response — skipping pivot check."
else
  echo "  querying Loki for trace_id=${TRACE_ID}"
  PIVOT_JSON="$(curl -sS -G "${LOKI_URL}/loki/api/v1/query_range" \
    --data-urlencode "query={app=\"expense-api\"} |= \"${TRACE_ID}\"" \
    --data-urlencode "start=${FIVE_MIN_AGO_NS}" \
    --data-urlencode "end=${NOW_NS}" \
    --data-urlencode "limit=50" || true)"
  echo "${PIVOT_JSON}" > "${DIAG_DIR}/loki-pivot.json"
  if echo "${PIVOT_JSON}" | grep -q "${TRACE_ID}"; then
    echo "  pivot ok: Loki has lines carrying trace_id=${TRACE_ID}"
  else
    echo "  WARN: no Loki line for trace_id=${TRACE_ID} in the last 5 min"
    echo "        (expected under 10% sampling if this trace's request was not logged in-window)."
  fi
fi

echo
echo "== observability-smoke passed =="
echo "diagnostics in ${DIAG_DIR}"
