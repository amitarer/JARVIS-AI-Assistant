"""JSON logs intentionally omit conversation text, arguments and secrets."""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for name in ("task_id", "tool", "status", "error_type"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(directory: Path, level: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jarvis")
    logger.setLevel(level)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(directory / "operations.jsonl", maxBytes=1_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
