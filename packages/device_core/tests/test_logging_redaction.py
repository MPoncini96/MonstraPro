import json

from device_core.db.session import Database
from device_core.logging import attach_db_handler, configure_logging, get_logger, redact
from device_core.repositories.execution_log import ExecutionLogRepository


def test_redact_recursively_masks_secret_shaped_keys():
    payload = {
        "status": "ok",
        "alpaca_api_key": "AKPUBLIC123",
        "nested": {
            "password": "hunter2",
            "authorization": "Bearer xyz",
            "safe_field": "keep-me",
        },
        "list_field": [{"credential_token": "abc"}, {"fine": "value"}],
    }

    redacted = redact(payload)

    assert redacted["status"] == "ok"
    assert redacted["alpaca_api_key"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["authorization"] == "***REDACTED***"
    assert redacted["nested"]["safe_field"] == "keep-me"
    assert redacted["list_field"][0]["credential_token"] == "***REDACTED***"
    assert redacted["list_field"][1]["fine"] == "value"


def test_console_log_line_is_redacted(config, capsys):
    configure_logging(config)
    logger = get_logger("test.redaction.console")

    logger.info("connected to alpaca", api_key="AKPUBLIC123", status="ok")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["api_key"] == "***REDACTED***"
    assert record["status"] == "ok"
    assert "AKPUBLIC123" not in line


def test_db_persisted_log_is_redacted(config):
    configure_logging(config)
    db = Database(config)
    logs = ExecutionLogRepository(db)

    logger_name = "test.redaction.db"
    attach_db_handler(logger_name, logs)
    logger = get_logger(logger_name)

    logger.warning("credential rotation failed", api_secret="SUPERSECRET456", component="worker")

    [record] = logs.recent(limit=10)
    assert record["context_json"]["api_secret"] == "***REDACTED***"
    assert "SUPERSECRET456" not in str(record)
