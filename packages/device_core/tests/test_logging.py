import json

from device_core.config import load_config
from device_core.db.database import Database
from device_core.logging import attach_db_handler, configure_logging, get_logger


def test_get_logger_emits_structured_json(tmp_path, capsys):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    configure_logging(config)
    logger = get_logger("test.device_core.structured")

    logger.info("worker started", status="completed", bot_count=3)

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["message"] == "worker started"
    assert record["status"] == "completed"
    assert record["bot_count"] == 3
    assert record["level"] == "INFO"


def test_attach_db_handler_persists_to_execution_log(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    configure_logging(config)
    db = Database(config)

    logger_name = "test.device_core.db_handler"
    attach_db_handler(logger_name, db)
    logger = get_logger(logger_name)

    logger.warning("connectivity degraded", status="degraded", component="worker")

    with db.session() as session:
        from device_core.db.models import ExecutionLog

        rows = session.query(ExecutionLog).all()
        assert len(rows) == 1
        assert rows[0].message == "connectivity degraded"
        assert rows[0].level == "WARNING"
        assert rows[0].context_json == {"status": "degraded", "component": "worker"}
