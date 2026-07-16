"""Small CLI that validates a DeductionClassifyRequest JSON file.

This module is the only place in the sidecar allowed to call ``print``
(the T20 ruff rule is disabled here via per-file-ignores).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from .models import DeductionClassifyRequest


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: expense-ai <request.json>", file=sys.stderr)
        return 2

    path = Path(args[0])
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        request = DeductionClassifyRequest.model_validate_json(raw)
    except ValidationError as exc:
        print(f"error: invalid request JSON: {exc}", file=sys.stderr)
        return 1

    print(request.model_dump_json(by_alias=True))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
