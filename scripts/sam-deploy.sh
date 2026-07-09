#!/usr/bin/env bash
# W5D4 — build and deploy the merchant lookup serverless stack.
# Requires: aws (with valid SSO session), sam, mvn, docker.
# Real AWS access keys are NOT accepted; use SSO (AWS_PROFILE=<sso-profile>).

set -euo pipefail

STAGE="${STAGE:-dev}"
STACK="${STACK:-expense-lambda-${STAGE}}"
REGION="${AWS_REGION:-us-east-1}"

# Org SCP-mandated tags. Deploy will be denied without all three.
TRAINEE_TAG="${TRAINEE_TAG:-pranav-kuchibhotla}"
TEAM_TAG="${TEAM_TAG:-womm}"
ENVIRONMENT_TAG="${ENVIRONMENT_TAG:-training}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== W5D4 sam-deploy =="
echo "STAGE=${STAGE}"
echo "STACK=${STACK}"
echo "REGION=${REGION}"
echo "TRAINEE_TAG=${TRAINEE_TAG}"
echo "TEAM_TAG=${TEAM_TAG}"
echo "ENVIRONMENT_TAG=${ENVIRONMENT_TAG}"
echo

if ! aws sts get-caller-identity --output text >/dev/null 2>&1; then
  cat >&2 <<'EOF'
[sam-deploy] AWS credentials not available.

Configure SSO once (do NOT use long-lived access keys):
  aws configure sso
  aws sso login --profile <your-sso-profile>
  export AWS_PROFILE=<your-sso-profile>
  aws sts get-caller-identity

Then re-run this script.
EOF
  exit 2
fi

STACK_STATUS="$(aws cloudformation describe-stacks \
  --stack-name "${STACK}" \
  --region "${REGION}" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || true)"

if [[ "${STACK_STATUS}" == "ROLLBACK_COMPLETE" ]]; then
  cat >&2 <<EOF
[sam-deploy] Stack ${STACK} is in ROLLBACK_COMPLETE.
CloudFormation cannot update a stack in this state.

Delete it first (only if you own it and it holds no real data):
  aws cloudformation delete-stack --stack-name "${STACK}" --region "${REGION}"
  aws cloudformation wait stack-delete-complete --stack-name "${STACK}" --region "${REGION}"

Or re-run with a new STACK name:
  STACK=${STACK}-\$(date -u +%s) ./scripts/sam-deploy.sh

Refusing to auto-delete without your approval.
EOF
  exit 1
fi

echo "[1/5] sam validate --lint"
sam validate --lint

echo "[2/5] mvn -B -ntp test"
mvn -B -ntp test

echo "[3/5] mvn -B -ntp package"
mvn -B -ntp package -DskipTests

echo "[4/5] sam build --use-container"
sam build --use-container

SAMCONFIG="${ROOT}/samconfig.toml"
if [[ ! -f "$SAMCONFIG" ]]; then
  cat >&2 <<EOF
[sam-deploy] samconfig.toml not found at repo root.

This deploy uses --resolve-s3 and passes all params on the CLI so we do NOT
commit samconfig.toml. If SAM asks for guided setup, run once locally:
  sam deploy --guided --stack-name ${STACK} --region ${REGION} \\
             --parameter-overrides StageName=${STAGE}
then answer "N" when it asks to save arguments to samconfig.toml.
EOF
fi

echo "[5/5] sam deploy"
sam deploy \
  --stack-name "${STACK}" \
  --region "${REGION}" \
  --parameter-overrides \
    "StageName=${STAGE}" \
    "TraineeTag=${TRAINEE_TAG}" \
    "TeamTag=${TEAM_TAG}" \
    "EnvironmentTag=${ENVIRONMENT_TAG}" \
    "LogRetentionDays=${LOG_RETENTION_DAYS}" \
  --tags \
    "trainee=${TRAINEE_TAG}" \
    "team=${TEAM_TAG}" \
    "environment=${ENVIRONMENT_TAG}" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --resolve-s3 \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

echo
echo "== CloudFormation outputs =="
aws cloudformation describe-stacks \
  --stack-name "${STACK}" \
  --region "${REGION}" \
  --query 'Stacks[0].Outputs' \
  --output table

echo
echo "== Smoke test command =="
echo "  STAGE=${STAGE} STACK=${STACK} AWS_REGION=${REGION} ./scripts/sam-smoke.sh"
