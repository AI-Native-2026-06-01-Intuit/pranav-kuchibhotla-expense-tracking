"""Static validation of the expense-agent-svc CI workflow.

Every `uses:` line MUST be pinned to a full 40-character commit SHA
(the ``@sha`` form). We assert that at parse time so a future edit
that introduces `@v4` or a floating tag fails PR review.

We also enforce the shape the rubric requires: PR + main-push
triggers with path filters, Postgres 16 service, uv sync --frozen,
ruff + strict mypy + coverage floor 85, deterministic gate present
*without* EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1, external RAGAS
gate with the --external flag and *without* the local-skip flag,
frontend test/typecheck/lint/build, Docker build from repo root, real
account 726695008378 in the ECR URI (never 123456789012, never
`:latest`), CFN validate-template, no deployment commands, and no
committed secrets.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "expense_agent_svc-ci.yml"
)


def _text() -> str:
    return _WORKFLOW.read_text()


# ---------- Existence + naming ----------


def test_workflow_exists() -> None:
    assert _WORKFLOW.exists()


def test_workflow_name_is_expense_agent_svc_ci() -> None:
    text = _text()
    assert re.search(r"^name:\s*expense-agent-svc-ci\s*$", text, flags=re.MULTILINE)


# ---------- Triggers + path filters ----------


def test_pr_and_main_push_triggers_present() -> None:
    text = _text()
    assert "pull_request:" in text
    assert "push:" in text
    assert re.search(r"branches:\s*\[main\]", text)


def test_path_filters_cover_agent_ai_mcp_web_and_workflow() -> None:
    text = _text()
    for path_filter in (
        '"expense-agent-svc/**"',
        '"expense-ai/**"',
        '"expense-mcp-server/**"',
        '"expense-web/**"',
        '".github/workflows/expense_agent_svc-ci.yml"',
    ):
        assert path_filter in text, f"path filter missing: {path_filter}"


# ---------- Pinned action SHAs ----------


_USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", flags=re.MULTILINE)
_ACTION_SHA = re.compile(r"^[^@]+@(?P<ref>[0-9a-f]{40})$")


def _uses_refs() -> list[str]:
    return [m.group(1) for m in _USES_LINE.finditer(_text())]


def test_every_external_action_reference_is_a_full_sha() -> None:
    refs = _uses_refs()
    assert refs, "workflow must reference at least one action"
    for ref in refs:
        # Reusable local workflows are allowed to use a repo-relative path.
        if ref.startswith("./"):
            continue
        assert _ACTION_SHA.match(ref), (
            f"action reference {ref!r} is not pinned to a full 40-char commit SHA"
        )


def test_no_floating_action_tags() -> None:
    text = _text()
    for pattern in (r"uses:\s*\S+@v[0-9]", r"uses:\s*\S+@main", r"uses:\s*\S+@master"):
        assert not re.search(pattern, text), f"found floating tag reference: {pattern}"


# ---------- Postgres service + uv + gates ----------


def test_postgres16_service_present() -> None:
    text = _text()
    assert "postgres:16" in text
    assert "pg_isready" in text
    # test-only credentials only.
    assert "POSTGRES_USER: postgres" in text
    assert "POSTGRES_PASSWORD: postgres" in text


def test_uv_sync_frozen_present() -> None:
    text = _text()
    assert "uv sync --frozen" in text


def test_ruff_and_ruff_format_check_present() -> None:
    text = _text()
    assert "uv run ruff check" in text
    assert "uv run ruff format --check" in text


def test_strict_mypy_covers_src_tests_evals() -> None:
    text = _text()
    assert "uv run mypy --strict src/ tests/ evals/" in text


def test_pytest_coverage_floor_is_85() -> None:
    text = _text()
    assert "--cov-fail-under=85" in text


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_deterministic_eval_gate_present_without_local_skip() -> None:
    text = _text()
    assert "python -m expense_agent_svc.scripts.eval --gate" in text
    # And the deterministic job must NOT export the local-skip flag —
    # the deterministic gate never requires external credentials.
    # (Comments may still explain the policy.)
    quality_section = text.split("external-eval:", maxsplit=1)[0]
    assert "EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP" not in _uncommented(quality_section)


def test_external_ragas_gate_present() -> None:
    text = _text()
    assert "expense_agent_svc.scripts.eval --gate --external" in text
    # Never expose the local-skip flag in CI (comments notwithstanding).
    assert "EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP" not in _uncommented(text)


# ---------- Frontend ----------


def test_frontend_ci_uses_expected_scripts() -> None:
    text = _text()
    assert "npm ci" in text
    assert "npm run test -- --run" in text
    assert "npm run typecheck" in text
    assert "npm run lint" in text
    assert "npm run build" in text


# ---------- Docker + ECR + CFN ----------


def test_docker_build_uses_repo_root_context_and_agent_dockerfile() -> None:
    text = _text()
    # The docker/build-push-action inputs specify context: . and
    # file: expense-agent-svc/Dockerfile.
    assert re.search(r"context:\s*\.", text)
    assert "expense-agent-svc/Dockerfile" in text


def test_actual_ecr_account_is_used() -> None:
    text = _text()
    assert "726695008378" in text
    assert "123456789012" not in text


def test_no_latest_image_tag_in_push_steps() -> None:
    """No workflow step may build/push/tag a `:latest` image.

    Comments may still explain the policy ("NEVER pushes :latest"),
    so we filter out comment lines before searching.
    """
    text = _text()
    assert not re.search(r"expense-agent-svc:latest", text)
    stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert ":latest" not in stripped


def test_ecr_preflight_step_present() -> None:
    text = _text()
    assert "ecr_preflight.sh" in text
    assert "describe-repositories" not in text  # done inside the script
    # No creation from CI, ever.
    assert "ecr create-repository" not in text


def test_config_bump_job_waits_for_build_push() -> None:
    text = _text()
    # bump-config `needs: build-and-push`.
    assert re.search(r"bump-config:.*?needs:\s*build-and-push", text, flags=re.DOTALL)


def test_merge_job_is_restricted_to_main_push() -> None:
    text = _text()
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in text


def test_oidc_permissions_on_push_and_validate_jobs() -> None:
    text = _text()
    # id-token: write appears at least twice (aws-validate + build-and-push).
    assert text.count("id-token: write") >= 2


def test_cloudformation_validate_template_present() -> None:
    text = _text()
    assert "aws cloudformation validate-template" in text
    # Never `deploy` / `create-stack` / `update-stack` from CI.
    for forbidden in ("cloudformation deploy", "create-stack", "update-stack"):
        assert forbidden not in text


def test_no_argo_apply_from_ci() -> None:
    text = _text()
    # The manifest gate must not depend on `kubectl apply` in any form
    # (including --dry-run=client, which still triggers server discovery
    # in newer kubectl versions and would fail without a reachable API
    # server). All Kubernetes schema validation now runs through
    # kubeconform against the Kustomize-rendered manifest file.
    for forbidden in ("argocd app sync", "argocd app create", "kubectl apply"):
        assert forbidden not in text, f"forbidden command still referenced: {forbidden!r}"


# ---------- Kubernetes manifest validation via kubeconform -------------


def test_manifest_gate_uses_kubeconform() -> None:
    text = _text()
    assert "kubeconform" in text, "deploy-static job must run kubeconform"


def test_kubeconform_version_is_pinned() -> None:
    text = _text()
    # An exact version pin, not a floating tag / branch.
    match = re.search(r'KUBECONFORM_VERSION:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', text)
    assert match is not None, "KUBECONFORM_VERSION must be pinned to an exact semver"
    # The pinned version must be consumed by the download URL via the
    # env var (no hardcoded floating alternative).
    assert (
        "kubeconform/releases/download/v${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz"
        in text
    ), "kubeconform download URL must reference the pinned KUBECONFORM_VERSION env var"
    # And no floating "latest" release URL exists as a fallback.
    assert "kubeconform/releases/latest" not in text


def test_kubeconform_checksum_is_verified_before_execution() -> None:
    text = _text()
    # Pinned checksum literal (64 hex chars) is present and consumed by
    # sha256sum -c before extraction/execution.
    match = re.search(r'KUBECONFORM_SHA256:\s*"([0-9a-f]{64})"', text)
    assert match is not None, "KUBECONFORM_SHA256 must be a full 64-char SHA-256 literal"
    assert "sha256sum -c" in text, (
        "downloaded kubeconform archive must be verified with sha256sum -c"
    )
    # The verification step must reference the pinned checksum variable.
    assert "${KUBECONFORM_SHA256}" in text


def test_kubeconform_uses_kustomize_rendered_manifest() -> None:
    text = _text()
    # Kustomize render still writes the same file that kubeconform reads.
    assert "kustomize build expense-agent-svc/gitops/overlays/prod" in text
    assert "/tmp/expense-agent-svc-prod.yaml" in text
    # kubeconform is invoked against exactly that rendered file.
    assert re.search(
        r"kubeconform[\s\S]*?/tmp/expense-agent-svc-prod\.yaml",
        text,
    ), "kubeconform must validate the Kustomize-rendered manifest file"


def test_kubeconform_invocation_has_strict_and_summary() -> None:
    text = _text()
    assert "-strict" in text
    assert "-summary" in text


def test_kubeconform_ignores_missing_crd_schemas_explicitly() -> None:
    text = _text()
    # Argo CRDs and other custom schemas may not ship with kubeconform;
    # this flag must be present and the choice must be documented.
    assert "-ignore-missing-schemas" in text


def test_manifest_gate_does_not_require_live_api_server() -> None:
    text = _text()
    # Guardrails: nothing in the manifest gate touches a real cluster or
    # obtains cluster credentials. kubectl is no longer installed and
    # `kubectl apply` is gone entirely (see test_no_argo_apply_from_ci).
    for forbidden in (
        "kubectl apply",
        "kubectl version",
        "kubectl cluster-info",
        "aws eks update-kubeconfig",
        "argocd login",
        "argocd app sync",
    ):
        assert forbidden not in text, f"live-cluster command still referenced: {forbidden!r}"


def test_manifest_gate_does_not_use_unpinned_action_or_container() -> None:
    text = _text()
    # No community kubeconform action, and no floating container tag.
    assert "yannh/kubeconform-action" not in text
    assert "ghcr.io/yannh/kubeconform" not in text
    assert "kubeconform:latest" not in text


def test_no_secret_literals_in_workflow() -> None:
    text = _text()
    for pattern in ("sk-ant-", "lsv2_pt_", "eyJhbGciOi"):
        assert pattern not in text


# ---------- Job dependency shape ----------


def test_quality_job_precedes_docker_and_external_and_deploy_static() -> None:
    text = _text()
    # Every dependent job lists `needs: quality`.
    for job in ("docker", "external-eval", "deploy-static", "aws-validate"):
        assert re.search(
            rf"^\s*{re.escape(job)}:.*?needs:\s*quality",
            text,
            flags=re.MULTILINE | re.DOTALL,
        ), f"{job} should have `needs: quality`"
