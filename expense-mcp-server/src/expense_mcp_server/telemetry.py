"""Structured logging configuration for the expense MCP server.

Two hard constraints drive this module:

* ``stdout`` is reserved for the stdio JSON-RPC framing. Any log line
  emitted there would corrupt the client-facing protocol stream, so
  every logger — both stdlib and ``structlog`` — is forced onto
  ``sys.stderr``.
* ``print`` is banned in server code. A ruff ``T20`` rule catches
  accidental ``print`` calls; tests further assert stdout cleanliness
  when the server is exercised through a subprocess.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Wire stdlib logging and structlog to emit JSON on stderr only."""
    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(level)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stderr_handler)
    root.setLevel(level)

    # Silence libraries that log to stdout under some configurations.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name``."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
