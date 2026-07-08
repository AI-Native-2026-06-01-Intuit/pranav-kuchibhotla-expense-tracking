#!/usr/bin/env bash
# W5D4 — smoke test the deployed merchant lookup stack against real AWS.
# Verifies the happy path (200/404), the API Gateway route-miss (404),
# CloudWatch log delivery, and x-correlation-id echo where possible.

set -euo pipefail

STAGE="${STAGE:-dev}"
STACK="${STACK:-expense-lambda-${STAGE}}"
REGION="${AWS_REGION:-us-east-1}"

MERCHANT_ID="${MERCHANT_ID:-mer_synth_001}"
CORR_ID="smoke-$(date -u +%Y%m%dT%H%M%SZ)-$$"
BODY_FILE="/tmp/sam-smoke-body"

echo "== W5D4 sam-smoke =="
echo "STAGE=${STAGE}  STACK=${STACK}  REGION=${REGION}"
echo "MERCHANT_ID=${MERCHANT_ID}  CORR_ID=${CORR_ID}"
echo

if ! aws sts get-caller-identity --output text >/dev/null 2>&1; then
  echo "[sam-smoke] AWS credentials not available. Run 'aws sso login' first." >&2
  exit 2
fi

HTTP_API_URL="$(aws cloudformation describe-stacks \
  --stack-name "${STACK}" \
  --region "${REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='HttpApiUrl'].OutputValue" \
  --output text 2>/dev/null || true)"

if [[ -z "${HTTP_API_URL}" || "${HTTP_API_URL}" == "None" ]]; then
  echo "[sam-smoke] Could not resolve HttpApiUrl from stack ${STACK}." >&2
  echo "            Is the stack deployed in region ${REGION}?" >&2
  aws cloudformation describe-stacks --stack-name "${STACK}" --region "${REGION}" \
    --query 'Stacks[0].StackStatus' --output text >&2 || true
  exit 3
fi

echo "HttpApiUrl=${HTTP_API_URL}"
echo

echo "[1/4] GET /merchants/${MERCHANT_ID}"
: > "${BODY_FILE}"
HDR_FILE="/tmp/sam-smoke-headers"
: > "${HDR_FILE}"
STATUS="$(curl -sS -o "${BODY_FILE}" -D "${HDR_FILE}" -w '%{http_code}' \
  -H "x-correlation-id: ${CORR_ID}" \
  -H 'accept: application/json' \
  "${HTTP_API_URL}/merchants/${MERCHANT_ID}" || true)"

echo "  status=${STATUS}"
echo "  body:"
sed 's/^/    /' "${BODY_FILE}" || true
echo "  response headers:"
sed 's/^/    /' "${HDR_FILE}" || true

if [[ "${STATUS}" != "200" && "${STATUS}" != "404" ]]; then
  echo "[sam-smoke] Unexpected status ${STATUS} — expected 200 (seeded) or 404 (no seed)." >&2
  exit 4
fi

# Best-effort correlation-id echo check.
if ! grep -Fi "${CORR_ID}" "${HDR_FILE}" >/dev/null 2>&1; then
  echo "[sam-smoke] WARN: x-correlation-id not found in response headers (may be stripped by API Gateway)."
else
  echo "  x-correlation-id echoed: ok"
fi

echo
echo "[2/4] GET /merchants/  (expecting 404 route-miss)"
MISS_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' \
  "${HTTP_API_URL}/merchants/" || true)"
echo "  status=${MISS_STATUS}"
if [[ "${MISS_STATUS}" != "404" ]]; then
  echo "[sam-smoke] WARN: expected 404 route miss for /merchants/, got ${MISS_STATUS}."
fi

echo
echo "[3/4] CloudWatch REPORT check"
LOG_GROUP="/aws/lambda/expense-merchant-lookup-${STAGE}"
sleep 8  # give logs time to flush
RECENT="$(aws logs filter-log-events \
  --region "${REGION}" \
  --log-group-name "${LOG_GROUP}" \
  --start-time "$(( ($(date -u +%s) - 300) * 1000 ))" \
  --filter-pattern 'REPORT' \
  --max-items 5 \
  --query 'events[].message' \
  --output text 2>/dev/null || true)"
if [[ -z "${RECENT}" ]]; then
  echo "[sam-smoke] WARN: no recent REPORT lines found in ${LOG_GROUP} within last 5 min." >&2
else
  echo "  found REPORT lines:"
  echo "${RECENT}" | sed 's/^/    /'
fi

echo
echo "[4/4] Correlation-id search in logs"
CORR_MATCH="$(aws logs filter-log-events \
  --region "${REGION}" \
  --log-group-name "${LOG_GROUP}" \
  --start-time "$(( ($(date -u +%s) - 300) * 1000 ))" \
  --filter-pattern "${CORR_ID}" \
  --max-items 3 \
  --query 'events[].message' \
  --output text 2>/dev/null || true)"
if [[ -z "${CORR_MATCH}" ]]; then
  echo "[sam-smoke] WARN: correlation id ${CORR_ID} not (yet) visible in log group ${LOG_GROUP}."
else
  echo "  correlation id found in logs:"
  echo "${CORR_MATCH}" | sed 's/^/    /'
fi

echo
echo "== W5D4 smoke complete =="
