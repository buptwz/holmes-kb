"""Holmes structured logging configuration.

Reads HOLMES_LOG_LEVEL environment variable (default: INFO).
"""

import logging
import os
import sys
from typing import Optional


def configure_logging(level: Optional[str] = None) -> None:
    """Configure Holmes logging.

    Args:
        level: Log level string. Falls back to HOLMES_LOG_LEVEL env var, then INFO.
    """
    log_level_str = level or os.environ.get("HOLMES_LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger("holmes")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a Holmes namespaced logger.

    Args:
        name: Logger name, will be prefixed with 'holmes.'.

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(f"holmes.{name}")
