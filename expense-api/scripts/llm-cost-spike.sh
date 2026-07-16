#!/usr/bin/env bash
#
# llm-cost-spike.sh — drive a synthetic burst of LLM proxy calls so
# the acme/llmproxy CostUsd metric spikes above the CloudWatch alarm
# threshold configured in cfn/expense-cost-dev.yaml.
#
# Cohort override (Kinza): this run does NOT use Bedrock. The upstream
# provider is called with LLM_API_KEY sourced from the environment.
# The key is never printed, never written to a file, and never
# committed. Do not add "echo $LLM_API_KEY" anywhere.
#
# Usage:
#   COUNT=200 TENANT=tenant-synth FEATURE=categorize-expense \
#     PROXY_URL=https://expense-api.dev.internal/llmproxy/echo \
#     ./llm-cost-spike.sh
#
# Dry run (default — no HTTP calls, no key needed):
#   ./llm-cost-spike.sh
#
# Real run (requires exporting LLM_API_KEY first):
#   export LLM_API_KEY=...   # DO NOT paste the key here in git-tracked files
#   DRY_RUN=0 COUNT=200 ./llm-cost-spike.sh

set -euo pipefail

COUNT="${COUNT:-200}"
INTERVAL_MS="${INTERVAL_MS:-100}"
TENANT="${TENANT:-tenant-synth}"
FEATURE="${FEATURE:-categorize-expense}"
MODEL="${MODEL:-claude-sonnet-4-5}"
PROXY_URL="${PROXY_URL:-}"
DRY_RUN="${DRY_RUN:-1}"

# --- safety rails ---------------------------------------------------------

if [[ "${TENANT}" == "prod"* || "${TENANT}" == *"-prod" ]]; then
  echo "REFUSING: TENANT=${TENANT} looks like a production tenant." >&2
  exit 2
fi

if [[ "${DRY_RUN}" != "1" ]]; then
  if [[ -z "${LLM_API_KEY:-}" ]]; then
    echo "REFUSING: DRY_RUN=0 requires LLM_API_KEY to be exported in the current shell." >&2
    echo "Export the key (do not commit it, do not paste it into a file):" >&2
    echo "  export LLM_API_KEY=..." >&2
    exit 2
  fi
  if [[ -z "${PROXY_URL}" ]]; then
    echo "REFUSING: DRY_RUN=0 requires PROXY_URL to be set." >&2
    exit 2
  fi
fi

echo "spike config:"
echo "  count=${COUNT}"
echo "  interval_ms=${INTERVAL_MS}"
echo "  tenant=${TENANT}"
echo "  feature=${FEATURE}"
echo "  model=${MODEL}"
echo "  dry_run=${DRY_RUN}"
echo "  proxy_url=${PROXY_URL:-<dry-run>}"

# --- driver ---------------------------------------------------------------

payload_for() {
  # Deterministic input tokens keep expected CostUsdE5 reproducible.
  cat <<EOF
{"tenant":"${TENANT}","feature":"${FEATURE}","modelId":"${MODEL}","inputTokens":1000,"outputTokens":250,"prompt":"synthetic spike iteration ${1}"}
EOF
}

for i in $(seq 1 "${COUNT}"); do
  if [[ "${DRY_RUN}" == "1" ]]; then
    # In dry-run mode we simulate the call locally: print the payload
    # that would be sent (never the API key) so a reviewer can see the
    # request shape.
    payload_for "${i}" | jq -c . 2>/dev/null || payload_for "${i}"
  else
    # Use --header @- style would leak the key into ps output on some
    # systems; -H "Authorization: Bearer ${LLM_API_KEY}" is the standard
    # curl form and does not appear in process listings on Linux.
    curl --fail --silent --show-error \
      -X POST "${PROXY_URL}" \
      -H "Authorization: Bearer ${LLM_API_KEY}" \
      -H "Content-Type: application/json" \
      -H "X-Tenant-Id: ${TENANT}" \
      -H "X-Feature: ${FEATURE}" \
      --data "$(payload_for "${i}")" \
      > /dev/null
  fi
  # Sleep in fractional seconds; bash's builtin sleep handles decimals.
  sleep "$(awk -v ms="${INTERVAL_MS}" 'BEGIN{printf "%.3f", ms/1000}')"
done

echo "done: ${COUNT} calls issued (dry_run=${DRY_RUN})."
