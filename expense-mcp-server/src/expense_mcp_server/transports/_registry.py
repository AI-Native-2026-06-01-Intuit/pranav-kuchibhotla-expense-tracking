"""Side-effect import module that registers all tools + resources on the ``mcp`` app.

Both transport entry points must import from here before calling
``mcp.run*`` so the decorators in ``tools/*.py`` and ``tools/_resources.py``
run and populate the FastMCP registry.
"""

from __future__ import annotations

from ..tools import _resources as _resources_module  # noqa: F401 - side effects register
from ..tools import llm as _llm  # noqa: F401
from ..tools import orders as _orders  # noqa: F401
from ..tools import rag as _rag  # noqa: F401
