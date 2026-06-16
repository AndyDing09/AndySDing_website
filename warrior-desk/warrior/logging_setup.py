"""Logging scaffold.

A single place to configure logging so every module shares the same format and
the same log file. Logging must never throw and never block a risk decision.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs") -> logging.Logger:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    logger = logging.getLogger("warrior")
    if _CONFIGURED:
        return logger

    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False

    fmt = logging.Formatter(_FORMAT)

    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    try:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(d / "warrior.log")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as exc:  # never let logging setup kill the agent
        logger.warning("Could not open log file (%s); continuing console-only.", exc)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "warrior") -> logging.Logger:
    if not name.startswith("warrior"):
        name = f"warrior.{name}"
    return logging.getLogger(name)
