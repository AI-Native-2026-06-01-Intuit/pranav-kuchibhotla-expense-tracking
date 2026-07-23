"""Static validation of the Phase 19 deployment artefacts.

The tests parse committed YAML and inspect committed shell/Python
scripts without executing them against AWS, Docker, or Kubernetes.
Live-tool checks (``docker build``, ``kustomize build``,
``aws cloudformation validate-template``) are run by the CI workflow
and by the local Phase 20 validation step in the plan.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import re
import sys as _sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_bump_module_path = Path(__file__).resolve().parents[1] / "scripts" / "bump_config_image.py"
_spec = _importlib_util.spec_from_file_location("bump_config_image", _bump_module_path)
assert _spec is not None and _spec.loader is not None
_bump = _importlib_util.module_from_spec(_spec)
_sys.modules["bump_config_image"] = _bump
_spec.loader.exec_module(_bump)

EXPECTED_IMAGE_NAME: str = _bump.EXPECTED_IMAGE_NAME
BumpError = _bump.BumpError
bootstrap_from_template = _bump.bootstrap_from_template
bump_kustomization = _bump.bump_kustomization

_ROOT = Path(__file__).resolve().parents[1]


# ---------- Dockerfile ------------------------------------------------------


def _dockerfile_text() -> str:
    return (_ROOT / "Dockerfile").read_text()


def test_dockerfile_uses_python312_slim_and_uv() -> None:
    text = _dockerfile_text()
    assert "FROM python:3.12-slim" in text
    assert "ghcr.io/astral-sh/uv" in text


def test_dockerfile_copies_three_local_projects() -> None:
    text = _dockerfile_text()
    for project in ("expense-ai", "expense-mcp-server", "expense-agent-svc"):
        assert f"COPY {project}" in text, f"{project} must be COPY'd into the image"


def test_dockerfile_runs_uv_sync_frozen_no_dev() -> None:
    text = _dockerfile_text()
    assert "uv sync --frozen --no-dev" in text


def test_dockerfile_drops_to_non_root() -> None:
    text = _dockerfile_text()
    assert "USER 65532" in text
    assert "chown -R 65532:65532" in text


def test_dockerfile_exposes_8080_and_declares_healthcheck() -> None:
    text = _dockerfile_text()
    assert "EXPOSE 8080" in text
    assert "HEALTHCHECK" in text
    assert "/healthz" in text


def test_dockerfile_does_not_bake_credentials() -> None:
    text = _dockerfile_text()
    # No plaintext secrets, no .env files, no AWS keys.
    for forbidden in (
        "sk-ant-",
        "lsv2_pt_",
        "eyJ",
        "aws_access_key_id",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert forbidden not in text, f"Dockerfile references {forbidden!r}"
    assert "COPY .env" not in text
    assert "COPY secrets" not in text


def test_dockerfile_entrypoint_is_expense_agent_svc_binary() -> None:
    text = _dockerfile_text()
    assert "/.venv/bin/expense-agent-svc" in text


# ---------- Dockerfile.dockerignore ----------------------------------------


def test_dockerfile_dockerignore_excludes_expense_web_and_venvs() -> None:
    text = (_ROOT / "Dockerfile.dockerignore").read_text()
    # The build must never drag in expense-web, expense-api, or any .venv.
    for pattern in ("expense-web", "expense-api", ".venv"):
        assert pattern in text, f"Dockerfile.dockerignore missing {pattern!r}"


# ---------- GitOps base + prod overlay ------------------------------------


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _load_all(path: Path) -> list[dict[str, Any]]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that keeps CloudFormation shortform intrinsics visible.

    The AWS CFN template uses ``!Ref``, ``!Sub``, ``!GetAtt`` etc.,
    which PyYAML's default resolver rejects. We accept them as plain
    strings/dicts so the shape assertions can navigate the tree.
    """


def _cfn_constructor(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> Any:
    del loader, tag_suffix
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_cfn_pluck(child) for child in node.value]
    if isinstance(node, yaml.MappingNode):
        return {_cfn_pluck(k): _cfn_pluck(v) for k, v in node.value}
    return None


def _cfn_pluck(node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_cfn_pluck(c) for c in node.value]
    if isinstance(node, yaml.MappingNode):
        return {_cfn_pluck(k): _cfn_pluck(v) for k, v in node.value}
    return None


yaml.add_multi_constructor("!", _cfn_constructor, Loader=_CfnLoader)


def _load_cfn(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.load(fh, Loader=_CfnLoader)
    assert isinstance(data, dict)
    return data


def test_gitops_base_has_deployment_service_configmap_secret() -> None:
    base = _ROOT / "gitops" / "base"
    assert (base / "deployment.yaml").exists()
    assert (base / "service.yaml").exists()
    assert (base / "configmap.yaml").exists()
    assert (base / "secret.yaml").exists()
    kustomization = _load(base / "kustomization.yaml")
    assert kustomization["kind"] == "Kustomization"
    assert {
        "deployment.yaml",
        "service.yaml",
        "configmap.yaml",
        "secret.yaml",
    } <= set(kustomization["resources"])


def test_deployment_has_probes_and_hardened_security() -> None:
    doc = _load(_ROOT / "gitops" / "base" / "deployment.yaml")
    spec = doc["spec"]["template"]["spec"]
    container = spec["containers"][0]
    assert container["ports"][0]["containerPort"] == 8080
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["startupProbe"]["httpGet"]["path"] == "/healthz"
    sec = container["securityContext"]
    assert sec["runAsNonRoot"] is True
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["readOnlyRootFilesystem"] is True
    assert "ALL" in sec["capabilities"]["drop"]
    pod_sec = spec["securityContext"]
    assert pod_sec["runAsNonRoot"] is True
    assert pod_sec["seccompProfile"]["type"] == "RuntimeDefault"


def test_deployment_image_uses_real_ecr_uri_not_latest() -> None:
    doc = _load(_ROOT / "gitops" / "base" / "deployment.yaml")
    image = doc["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image.startswith("726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc")
    assert not image.endswith(":latest")
    assert "123456789012" not in image


def test_deployment_never_carries_plaintext_secrets() -> None:
    # Only envFrom / secretRef — never inline env values with secret shapes.
    doc = _load(_ROOT / "gitops" / "base" / "deployment.yaml")
    container = doc["spec"]["template"]["spec"]["containers"][0]
    env_from = container["envFrom"]
    kinds = {next(iter(entry.keys())) for entry in env_from}
    assert kinds == {"configMapRef", "secretRef"}
    inline_env = container.get("env", [])
    for entry in inline_env:
        assert "sk-ant" not in str(entry.get("value", ""))
        assert "eyJ" not in str(entry.get("value", ""))


def test_secret_manifest_carries_only_key_names_no_values() -> None:
    secret = _load(_ROOT / "gitops" / "base" / "secret.yaml")
    assert secret["kind"] == "Secret"
    string_data = secret["stringData"]
    for key, value in string_data.items():
        assert isinstance(value, str)
        assert value == "", f"Secret {key} carries a value; must be empty placeholder"


def test_prod_overlay_pins_image_uri_and_rewrites_tag() -> None:
    overlay = _load(_ROOT / "gitops" / "overlays" / "prod" / "kustomization.yaml")
    assert overlay["namespace"] == "expense-svc"
    images = overlay["images"]
    ecr = images[0]
    assert ecr["name"] == "726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc"
    # newTag is a hex placeholder — the merge workflow rewrites it. No floating tags.
    new_tag = str(ecr["newTag"])
    assert new_tag != "latest"
    assert re.match(r"^[0-9a-f]{40}$", new_tag), (
        "prod overlay newTag must be a 40-hex placeholder or a real git SHA"
    )


def test_prod_overlay_prod_replicas_three() -> None:
    overlay = _load(_ROOT / "gitops" / "overlays" / "prod" / "kustomization.yaml")
    replicas = overlay["replicas"][0]
    assert replicas["name"] == "expense-agent-svc"
    assert replicas["count"] == 3


# ---------- Argo Application ----------------------------------------------


def test_argo_application_shape() -> None:
    app = _load(_ROOT / "argo-apps" / "expense-agent-svc.yaml")
    assert app["apiVersion"] == "argoproj.io/v1alpha1"
    assert app["kind"] == "Application"
    assert app["metadata"]["name"] == "expense-agent-svc"
    assert app["metadata"]["namespace"] == "argocd"
    spec = app["spec"]
    assert spec["destination"]["namespace"] == "expense-svc"
    assert spec["destination"]["server"] == "https://kubernetes.default.svc"
    # Uses the real config repo remote observed on disk.
    assert (
        spec["source"]["repoURL"]
        == "https://github.com/AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-config.git"
    )
    assert spec["source"]["path"] == "expense-agent-svc/overlays/prod"
    # No example placeholders.
    text = (_ROOT / "argo-apps" / "expense-agent-svc.yaml").read_text()
    for forbidden in ("uptimecrew/platform-config", "example.com", "123456789012"):
        assert forbidden not in text
    # Automated sync + prune + selfHeal.
    automated = spec["syncPolicy"]["automated"]
    assert automated["prune"] is True
    assert automated["selfHeal"] is True


# ---------- CloudFormation Budget ------------------------------------------


def test_cfn_budget_shape() -> None:
    doc = _load_cfn(_ROOT / "cfn" / "agent-svc-budget.yaml")
    params = doc["Parameters"]
    # Values arrive as strings via _CfnLoader (short-form scalar
    # resolver); compare textually.
    assert str(params["MonthlyLimitUsd"]["Default"]) == "4000"
    assert params["ServiceRoleName"]["Default"] == "expense-agent-svc-role"
    resources = doc["Resources"]
    budget = resources["MonthlyBudget"]["Properties"]["Budget"]
    assert budget["BudgetLimit"]["Unit"] == "USD"
    assert budget["TimeUnit"] == "MONTHLY"

    action = resources["HardCapDenyAction"]["Properties"]
    assert action["NotificationType"] == "ACTUAL"
    assert str(action["ActionThreshold"]["Value"]) == "100"
    assert action["ActionThreshold"]["Type"] == "PERCENTAGE"
    assert action["ActionType"] == "APPLY_IAM_POLICY"
    assert action["ApprovalModel"] == "AUTOMATIC"


def test_cfn_template_has_no_placeholder_account_or_hardcoded_email() -> None:
    text = (_ROOT / "cfn" / "agent-svc-budget.yaml").read_text()
    assert "123456789012" not in text
    # NotificationEmail default must be empty — no hardcoded operator address.
    doc = _load_cfn(_ROOT / "cfn" / "agent-svc-budget.yaml")
    default = doc["Parameters"]["NotificationEmail"]["Default"]
    assert default == "" or default is None


# ---------- ECR preflight script ------------------------------------------


def test_ecr_preflight_script_names_the_repo_and_account() -> None:
    text = (_ROOT / "scripts" / "ecr_preflight.sh").read_text()
    assert "expense-agent-svc" in text
    assert "726695008378" in text
    # No `create-repository` in code — the script must never create
    # anything. (Comments explaining the policy are fine.)
    non_comment = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "create-repository" not in non_comment
    # Names the fail-closed error message required by the spec.
    assert "Required ECR repository" in text
    assert "Provision it through approved infrastructure" in text


# ---------- bump_config_image script --------------------------------------


def _write_fake_overlay(dir_path: Path, tag: str = "aaaa" * 10) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "images:\n"
        f"  - name: {EXPECTED_IMAGE_NAME}\n"
        f'    newTag: "{tag}"\n'
    )


def test_bump_rewrites_the_expected_image_only(tmp_path: Path) -> None:
    config_repo = tmp_path / "config-repo"
    overlay = config_repo / "expense-agent-svc" / "overlays" / "prod"
    _write_fake_overlay(overlay)
    sha = "1" * 40
    bump_kustomization(overlay, sha)
    text = (overlay / "kustomization.yaml").read_text()
    assert f'newTag: "{sha}"' in text


def test_bump_rejects_bad_sha(tmp_path: Path) -> None:
    overlay = tmp_path / "expense-agent-svc" / "overlays" / "prod"
    _write_fake_overlay(overlay)
    with pytest.raises(BumpError):
        bump_kustomization(overlay, "not-a-sha")
    with pytest.raises(BumpError):
        bump_kustomization(overlay, "latest")


def test_bump_refuses_outside_service_directory(tmp_path: Path) -> None:
    overlay = tmp_path / "expense-api" / "overlays" / "prod"
    _write_fake_overlay(overlay)
    with pytest.raises(BumpError, match="expense-agent-svc"):
        bump_kustomization(overlay, "1" * 40)


def test_bump_missing_kustomization_raises(tmp_path: Path) -> None:
    overlay = tmp_path / "expense-agent-svc" / "overlays" / "prod"
    overlay.mkdir(parents=True)
    with pytest.raises(BumpError, match=r"kustomization\.yaml not found"):
        bump_kustomization(overlay, "1" * 40)


def test_bump_refuses_when_multiple_images_match(tmp_path: Path) -> None:
    overlay = tmp_path / "expense-agent-svc" / "overlays" / "prod"
    overlay.mkdir(parents=True)
    (overlay / "kustomization.yaml").write_text(
        "images:\n"
        f"  - name: {EXPECTED_IMAGE_NAME}\n"
        f'    newTag: "aaaa"\n'
        f"  - name: {EXPECTED_IMAGE_NAME}\n"
        f'    newTag: "bbbb"\n'
    )
    with pytest.raises(BumpError, match="found 2 images"):
        bump_kustomization(overlay, "1" * 40)


def test_bootstrap_from_template(tmp_path: Path) -> None:
    src = tmp_path / "template"
    src.mkdir()
    (src / "kustomization.yaml").write_text("kind: Kustomization\n")
    (src / "extra").mkdir()
    (src / "extra" / "hello.txt").write_text("hi")

    target = tmp_path / "config-repo" / "expense-agent-svc" / "overlays" / "prod"
    bootstrap_from_template(src, target)
    assert (target / "kustomization.yaml").exists()
    assert (target / "extra" / "hello.txt").read_text() == "hi"


def test_bootstrap_refuses_to_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "template"
    src.mkdir()
    (src / "kustomization.yaml").write_text("kind: Kustomization\n")

    target = tmp_path / "config-repo" / "expense-agent-svc" / "overlays" / "prod"
    target.mkdir(parents=True)
    (target / "existing.txt").write_text("do not clobber me")
    with pytest.raises(BumpError, match="non-empty"):
        bootstrap_from_template(src, target)


# ---------- Config repo remained untouched --------------------------------


def test_this_batch_did_not_modify_the_local_config_repo() -> None:
    """The local config repo path must be clean and on its original branch.

    We rely on the developer honouring the spec ("do not modify the
    local config repository"). This test is a defence-in-depth check
    that verifies (a) the path exists and (b) the working tree there
    is not dirty. If the path is not present we skip.
    """
    import subprocess

    config_path = Path.home() / "Documents" / "pranav-kuchibhotla-expense-config"
    if not config_path.exists():
        pytest.skip(f"config repo not checked out at {config_path}")
    proc = subprocess.run(
        ["git", "-C", str(config_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "", f"config repo at {config_path} is dirty:\n{proc.stdout}"
    # Existence of a `shutil.copytree` invocation elsewhere is what we
    # actually guard — the bump script's ``bootstrap_from_template``
    # only ever writes into the *CI job's* checkout, not this local
    # working copy. Nothing this test batch runs should modify that
    # directory.
