"""Structured logging, shared by all services.

A thin wrapper around the stdlib logging module that accepts structured
keyword fields the way Monstra-Worker/worker_logging.py does -
logger.info("message", status="completed", bot_id="alpha1") - and renders
each record as one JSON line on stdout, so systemd/journald captures
something machine-parseable without extra plumbing.

Any field whose key contains secret/password/token/api_key/authorization/
credential (case-insensitive, recursively through nested dicts/lists) is
redacted before the record exists anywhere - console or persisted - since
redaction happens once, in StructuredLogger.process(), the single point
where kwargs become the record's `fields`.

Persisting records to execution_log (ARCHITECTURE.md section 7) is opt-in
via attach_db_handler rather than the default, so configuring logging never
requires a live DeviceCore/DB instance.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from device_core.config import Config

if TYPE_CHECKING:
    from device_core.repositories.execution_log import ExecutionLogRepository

_RESERVED_KWARGS = {"exc_info", "stack_info", "stacklevel"}
_REDACT_KEY_MARKERS = ("secret", "password", "token", "api_key", "authorization", "credential")
_REDACTED_VALUE = "***REDACTED***"
_configured = False


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _REDACT_KEY_MARKERS)


def redact(value: Any) -> Any:
    """Recursively replace values whose dict key looks secret-shaped."""
    if isinstance(value, dict):
        return {k: (_REDACTED_VALUE if _should_redact(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    return value


class _StdoutHandler(logging.Handler):
    """Writes to whatever sys.stdout currently is, looked up per-emit.

    A plain logging.StreamHandler(sys.stdout) binds the stream object at
    construction time; combined with configure_logging()'s idempotency
    guard, that means the handler would keep writing to whichever
    sys.stdout was current the *first* time configure_logging() ran in
    this process - breaking output capture (e.g. pytest's capsys, which
    swaps sys.stdout per test) for every call after the first.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class StructuredLogger(logging.LoggerAdapter):
    """Lets callers write logger.info("message", key=value, ...) directly.

    Redacts secret-shaped fields here, once, before they become part of the
    LogRecord - every downstream consumer (console formatter, DB handler)
    sees only already-redacted data.
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        fields = {key: value for key, value in kwargs.items() if key not in _RESERVED_KWARGS}
        for key in fields:
            kwargs.pop(key)
        kwargs["extra"] = {"fields": redact(fields)}
        return msg, kwargs


def configure_logging(config: Config) -> None:
    """Idempotent: sets up the root logger's handler/level once per process."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(config.log_level)
    handler = _StdoutHandler()
    handler.setFormatter(_StructuredFormatter())
    root.handlers = [handler]
    _configured = True


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name), {})


def attach_db_handler(name: str, logs: "ExecutionLogRepository") -> None:
    """Optionally persist a logger's records to execution_log as they're
    emitted. Takes a logger *name* (not a StructuredLogger) so it attaches
    to the same underlying stdlib logger that get_logger(name) wraps.
    Fields arriving here are already redacted (see StructuredLogger.process).
    """

    class _ExecutionLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                fields = getattr(record, "fields", None) or {}
                logs.record(
                    level=record.levelname,
                    component=record.name,
                    message=record.getMessage(),
                    context=fields,
                )
            except Exception:
                pass  # logging must never raise

    logging.getLogger(name).addHandler(_ExecutionLogHandler())
