#!/usr/bin/env bash
# ECR preflight for expense-agent-svc.
#
# The merge-to-main workflow calls this before attempting `docker push`.
# The ECR repository must already exist — we never `aws ecr
# create-repository` from CI. If the repository is missing the script
# fails with a precise, operator-actionable message.

set -euo pipefail

REPO="${EXPENSE_AGENT_ECR_REPO:-expense-agent-svc}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${EXPENSE_AGENT_ECR_ACCOUNT:-726695008378}"

if ! command -v aws >/dev/null 2>&1; then
  echo "::error::aws CLI not available in PATH" >&2
  exit 2
fi

if ! aws ecr describe-repositories \
       --repository-names "${REPO}" \
       --region "${REGION}" \
       --output json >/dev/null 2>&1; then
  cat >&2 <<EOF
::error::Required ECR repository ${REPO} is not provisioned in account ${ACCOUNT_ID}. Provision it through approved infrastructure before rerunning the merge deployment.
EOF
  exit 1
fi

echo "ok: ECR repository ${REPO} is provisioned in account ${ACCOUNT_ID} (${REGION})"
