"""Rolling application log file: %APPDATA%/SaveDeck/savedeck.log.

The engine mirrors its log messages here so backups can be diagnosed after
the fact (especially when running silently in the tray). Uses only the
standard library; logging failures are swallowed - a log problem must never
break a backup.
"""
from __future__ import annotations

import logging
import logging.handlers
import os

from .config import app_dir

_LOGGER_NAME = "savedeck"
_MAX_BYTES = 1 << 20  # 1 MB per file before rotation
_BACKUPS = 3          # keep savedeck.log.1 .. savedeck.log.3
_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def get_log_path() -> str:
    return os.path.join(app_dir(), "savedeck.log")


def setup_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    try:
        handler = logging.handlers.RotatingFileHandler(
            get_log_path(), maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    except Exception:
        pass  # no writable log location: run without file logging
    return logger


def write_log(level: str, msg: str) -> None:
    """Append one engine log message to the rolling file (best effort)."""
    if level not in _LEVELS:
        return  # e.g. the internal 'refresh' signal stays UI-only
    try:
        setup_logger().log(_LEVELS[level], msg)
    except Exception:
        pass


def read_log_tail(max_lines: int = 200) -> str:
    """Return the last `max_lines` lines of the log ('' if there is none)."""
    try:
        with open(get_log_path(), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:]).rstrip("\n")
    except OSError:
        return ""