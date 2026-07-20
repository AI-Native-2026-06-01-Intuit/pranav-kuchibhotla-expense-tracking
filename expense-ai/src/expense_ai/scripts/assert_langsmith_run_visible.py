"""Assert that a retrieve_chunks call surfaces as a LangSmith run.

Usage::

    python -m expense_ai.scripts.assert_langsmith_run_visible

Reads credentials from the environment only; nothing is hardcoded. When any
required env var is missing and ``EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1`` is set,
the script prints a SKIPPED line and exits 0 so local/CI without real
secrets stays green.
"""

from __future__ import annotations

import os
import sys
import time

from expense_ai.rag import retrieve_chunks

_ALLOW_SKIP_ENV = "EXPENSE_AI_ALLOW_EXTERNAL_SKIP"
_REQUIRED = ("LANGSMITH_API_KEY", "EXPENSE_AI_PG_DSN")


def _project_name() -> str:
    return (
        os.environ.get("LANGSMITH_PROJECT")
        or os.environ.get("EXPENSE_AI_LANGSMITH_PROJECT")
        or "expense-ai-dev"
    )


def _missing_env() -> list[str]:
    return [name for name in _REQUIRED if not os.environ.get(name)]


def main() -> int:
    missing = _missing_env()
    if missing:
        if os.environ.get(_ALLOW_SKIP_ENV) == "1":
            print(
                f"SKIPPED: LangSmith visibility check — missing env: {missing}. "
                f"Set {_ALLOW_SKIP_ENV}=0 (or unset) with real credentials to enforce."
            )
            return 0
        print(f"FAIL: LangSmith visibility check missing required env: {missing}")
        return 2

    dsn = os.environ["EXPENSE_AI_PG_DSN"]
    question = "Is a business meal deductible?"
    print(f"Calling retrieve_chunks against LangSmith project={_project_name()}")
    retrieve_chunks(dsn=dsn, question=question, k=3)

    # Give LangSmith a moment to flush the trace batch.
    time.sleep(3)

    from langsmith import Client

    client = Client()
    project = _project_name()
    runs = list(
        client.list_runs(
            project_name=project,
            filter='eq(name, "expense_ai.retrieve_chunks")',
            limit=5,
        )
    )
    if not runs:
        print(
            f"FAIL: no LangSmith runs named 'expense_ai.retrieve_chunks' found in project {project}"
        )
        return 3
    print(f"OK: found {len(runs)} LangSmith run(s) in project {project}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
