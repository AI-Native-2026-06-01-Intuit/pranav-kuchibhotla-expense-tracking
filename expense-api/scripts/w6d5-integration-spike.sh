#!/usr/bin/env bash
# W6D5 integration spike: enqueues COUNT synthetic messages onto the
# expense-ingest SQS queue so the KEDA ScaledObject can be observed
# scaling the worker deployment from 0 -> N -> 0.
#
# DRY_RUN=1 (default) prints what would be sent and touches no AWS API.
# Set DRY_RUN=0 with QUEUE_URL exported to actually enqueue.
#
# No secrets are read or emitted. Tenant is hard-locked to tenant-synth.
set -euo pipefail

DRY_RUN="${DRY_RUN:-1}"
COUNT="${COUNT:-4000}"
TENANT="tenant-synth"
FEATURE="categorize-expense"
QUEUE_URL="${QUEUE_URL:-}"

log() { printf '[w6d5-spike] %s\n' "$*"; }

sample_message() {
  local i="$1"
  cat <<JSON
{"tenantId":"${TENANT}","feature":"${FEATURE}","merchant":"Merchant-${i}","amount":$(( (i % 500) + 1 )).0,"date":"2026-07-15","synthetic":true}
JSON
}

if [[ "$DRY_RUN" == "1" ]]; then
  log "DRY_RUN=1: no AWS calls will be made."
  log "COUNT=${COUNT}  TENANT=${TENANT}  FEATURE=${FEATURE}"
  log "QUEUE_URL (would-target)=${QUEUE_URL:-<unset>}"
  log "Sample of first 3 messages:"
  for i in 1 2 3; do
    printf '  '
    sample_message "$i"
  done
  log "Set DRY_RUN=0 and export QUEUE_URL to actually enqueue."
  exit 0
fi

if [[ -z "$QUEUE_URL" ]]; then
  log "ERROR: DRY_RUN=0 requires QUEUE_URL to be exported." >&2
  exit 2
fi

if ! command -v aws >/dev/null 2>&1; then
  log "ERROR: aws CLI not found on PATH." >&2
  exit 3
fi

log "LIVE mode: sending ${COUNT} messages to ${QUEUE_URL}"
for ((i = 1; i <= COUNT; i++)); do
  body="$(sample_message "$i")"
  aws sqs send-message \
    --queue-url "$QUEUE_URL" \
    --message-body "$body" \
    --message-attributes "Tenant={StringValue=${TENANT},DataType=String},Feature={StringValue=${FEATURE},DataType=String}" \
    >/dev/null
  if (( i % 100 == 0 )); then
    log "sent ${i}/${COUNT}"
  fi
done

log "done: enqueued ${COUNT} synthetic messages."
