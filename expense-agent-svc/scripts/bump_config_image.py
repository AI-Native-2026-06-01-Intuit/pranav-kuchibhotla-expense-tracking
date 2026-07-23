"""Bump the expense-agent-svc image tag in the sibling config repo.

Invoked by the merge-to-main CI workflow after a successful `docker
push`. The script:

1. Validates the git SHA is 40 lowercase hex characters and that the
   image ref is not floating (:latest, :main, empty).
2. Reads the config repo's ``expense-agent-svc/overlays/prod/
   kustomization.yaml`` file (or bootstraps it from the committed
   template if ``--allow-bootstrap`` is set), verifying the file lives
   under an expected agent-svc directory before touching it.
3. Rewrites the ``images: -name: <ecr>/expense-agent-svc newTag: <sha>``
   entry only. All other content is left untouched.
4. Writes the file back deterministically.

The script never runs ``git`` itself — the CI workflow is responsible
for committing and pushing the resulting change. Tests exercise the
script against a temporary fake config repo; no network, no real push.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_TAGS = frozenset({"latest", "main", "master"})

EXPECTED_IMAGE_NAME = "726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc"
EXPECTED_SERVICE_DIR = "expense-agent-svc"


class BumpError(RuntimeError):
    """Raised when the bump cannot be safely applied."""


def _assert_valid_sha(sha: str) -> None:
    if not _SHA_PATTERN.match(sha):
        raise BumpError(f"image-sha must be exactly 40 lowercase hex characters, got {sha!r}")
    if sha in _FORBIDDEN_TAGS:
        raise BumpError(f"image-sha must not be a floating tag: {sha!r}")


def _assert_agent_svc_directory(overlay_path: Path) -> None:
    """Refuse to edit anything outside the expected agent-svc tree."""
    parts = overlay_path.parts
    if EXPECTED_SERVICE_DIR not in parts:
        raise BumpError(
            f"overlay path must live under a {EXPECTED_SERVICE_DIR!r} directory; got {overlay_path}"
        )


def bump_kustomization(
    overlay_path: Path,
    sha: str,
    *,
    image_name: str = EXPECTED_IMAGE_NAME,
) -> None:
    """Rewrite the ``newTag`` line in the given overlay's kustomization."""
    _assert_valid_sha(sha)
    _assert_agent_svc_directory(overlay_path)

    kustomization = overlay_path / "kustomization.yaml"
    if not kustomization.exists():
        raise BumpError(f"kustomization.yaml not found at {kustomization}")

    text = kustomization.read_text()

    # Match:
    #     - name: <image_name>
    #       newTag: "<old>"
    # (indentation and quoting varies slightly; we accept the sibling
    # expense-api convention of `newTag: <bare>`).
    pattern = re.compile(
        rf"(?P<prefix>-\s*name:\s*{re.escape(image_name)}\s*\n\s*newTag:\s*)"
        rf"(?P<oldtag>\"?[^\"\n]+\"?)",
        flags=re.MULTILINE,
    )
    matches = pattern.findall(text)
    if not matches:
        raise BumpError(f"could not find an images: block for {image_name!r} in {kustomization}")
    if len(matches) > 1:
        raise BumpError(
            f"found {len(matches)} images: blocks for {image_name!r} — refusing "
            f"to guess which to bump"
        )

    new_text = pattern.sub(rf'\g<prefix>"{sha}"', text)
    if new_text == text:
        # No-op is not an error (the tag was already at sha), but we
        # still want the CI diff step to detect this and short-circuit.
        return
    kustomization.write_text(new_text)


def bootstrap_from_template(
    template_overlay: Path,
    target_service_dir: Path,
) -> None:
    """Copy the committed prod overlay template into the config repo.

    Only invoked when ``--allow-bootstrap`` is passed. Refuses to
    overwrite an existing target directory so we never step on a
    hand-authored overlay by accident.
    """
    _assert_agent_svc_directory(target_service_dir)
    if target_service_dir.exists() and any(target_service_dir.iterdir()):
        raise BumpError(f"refusing to bootstrap into a non-empty directory: {target_service_dir}")
    if not template_overlay.exists():
        raise BumpError(f"template not found at {template_overlay}")
    target_service_dir.mkdir(parents=True, exist_ok=True)
    for entry in template_overlay.iterdir():
        dest = target_service_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bump-config-image")
    parser.add_argument("--config-repo", type=Path, required=True)
    parser.add_argument("--overlay-path", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument(
        "--image-name",
        default=EXPECTED_IMAGE_NAME,
        help="ECR image the newTag line belongs to; must be the agent-svc image.",
    )
    parser.add_argument(
        "--allow-bootstrap",
        action="store_true",
        help="Copy the committed template overlay into the config repo when the "
        "target path does not yet exist. Refuses to overwrite non-empty targets.",
    )
    parser.add_argument(
        "--bootstrap-template",
        type=Path,
        default=None,
        help="Path to the committed overlay template used with --allow-bootstrap.",
    )
    args = parser.parse_args(argv)

    if args.image_name != EXPECTED_IMAGE_NAME:
        sys.stderr.write(
            f"error: refusing to bump image other than {EXPECTED_IMAGE_NAME!r} "
            f"(got {args.image_name!r})\n"
        )
        return 2

    overlay = (args.config_repo / args.overlay_path).resolve()
    try:
        _assert_agent_svc_directory(overlay)
    except BumpError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if not (overlay / "kustomization.yaml").exists():
        if not args.allow_bootstrap:
            sys.stderr.write(
                f"error: {overlay}/kustomization.yaml does not exist. Pass "
                "--allow-bootstrap --bootstrap-template <path> to seed the "
                "config repo from the committed template.\n"
            )
            return 2
        if args.bootstrap_template is None:
            sys.stderr.write("error: --allow-bootstrap requires --bootstrap-template\n")
            return 2
        try:
            bootstrap_from_template(args.bootstrap_template, overlay)
        except BumpError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2

    try:
        bump_kustomization(overlay, args.sha, image_name=args.image_name)
    except BumpError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    print(f"bumped {overlay}/kustomization.yaml newTag -> {args.sha}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
