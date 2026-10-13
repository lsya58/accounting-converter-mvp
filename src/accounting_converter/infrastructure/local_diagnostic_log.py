from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "accounting_converter.local"


def default_diagnostic_log_path() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        root = Path(local_appdata) / "AccountingConverter"
    else:
        root = Path.home() / ".local" / "state" / "AccountingConverter"
    return root / "logs" / "application.log"


def log_local_exception(
    operation: str,
    error: BaseException,
    *,
    log_path: Path | None = None,
) -> Path | None:
    """Write local-only diagnostics without logging accounting file contents."""
    path = log_path or default_diagnostic_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(LOGGER_NAME)
        logger.setLevel(logging.ERROR)
        handler = RotatingFileHandler(
            path,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
        try:
            logger.error(
                "%s failed: %s: %s",
                operation,
                type(error).__name__,
                str(error),
                exc_info=(type(error), error, error.__traceback__),
            )
        finally:
            logger.removeHandler(handler)
            handler.close()
        return path
    except Exception:
        # Diagnostic logging must never replace the original user-facing failure.
        return None
