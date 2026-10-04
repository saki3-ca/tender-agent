"""
Structured JSON logging module for ACNABIN Tender & Opportunity Intelligence Agent.
Outputs structured JSON lines to stdout for automatic capture by GitHub Actions.
"""

import sys
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include custom attributes added to record via extra={}
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message"
            } and not key.startswith("_"):
                log_entry[key] = val

        if record.exc_info:
            log_entry["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_logger(name: str = "acnabin_monitor", level: int = logging.INFO) -> logging.Logger:
    """Configures and returns a logger instance with JSON stdout formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


# Global default logger instance
logger = setup_logger("acnabin")
