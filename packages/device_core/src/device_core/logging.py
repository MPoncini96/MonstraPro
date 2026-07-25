"""Structured logging, shared by all services.

A thin wrapper around the stdlib logging module that accepts structured
keyword fields the way Monstra-Worker/worker_logging.py does -
``logger.info("message", status="completed", bot_id="alpha1")`` - and
renders each record as one JSON line on stdout, so systemd/journald
captures something machine-parseable without extra plumbing.

Persisting records to the execution_log table (ARCHITECTURE.md section 7)
is opt-in via attach_db_handler rather than the default, so configuring
logging never requires a live DB connection.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from device_core.config import Config

_RESERVED_KWARGS = {"exc_info", "stack_info", "stacklevel"}
_configured = False


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class StructuredLogger(logging.LoggerAdapter):
    """Lets callers write logger.info("message", key=value, ...) directly."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        fields = {key: value for key, value in kwargs.items() if key not in _RESERVED_KWARGS}
        for key in fields:
            kwargs.pop(key)
        kwargs["extra"] = {"fields": fields}
        return msg, kwargs


def configure_logging(config: Config) -> None:
    """Idempotent: sets up the root logger's handler/level once per process."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(config.log_level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_StructuredFormatter())
    root.handlers = [handler]
    _configured = True


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name), {})


def attach_db_handler(name: str, db: Any) -> None:
    """Optionally persist a logger's records to execution_log as they're emitted.

    Takes a logger *name* (not a StructuredLogger) so it can attach to the
    same underlying stdlib logger that get_logger(name) wraps.
    """

    class _ExecutionLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                fields = getattr(record, "fields", None) or {}
                db.log_execution(
                    level=record.levelname,
                    component=record.name,
                    message=record.getMessage(),
                    context=fields,
                )
            except Exception:
                pass  # logging must never raise

    logging.getLogger(name).addHandler(_ExecutionLogHandler())
