"""stdio transport entry point.

Bound to the ``expense-mcp-server`` console script. Registers all tools
+ resources through ``_registry`` and hands control to FastMCP's stdio
loop. stdout is reserved for the JSON-RPC frames; logs go to stderr.
"""

from __future__ import annotations

import argparse

from ..app import mcp
from ..telemetry import configure_logging
from . import _registry  # noqa: F401 - side-effect: registers tools


def main() -> None:
    """Console entry point for stdio transport."""
    parser = argparse.ArgumentParser(
        prog="expense-mcp-server",
        description="stdio MCP transport for the UptimeCrew expense surface.",
    )
    parser.parse_args()
    configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
