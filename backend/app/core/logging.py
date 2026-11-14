"""Structured logging helpers.

Every job keeps an in-memory ring buffer so the UI can show the exact log lines
that a processing run produced, while the same records go to stderr as JSON.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

_configured = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.addHandler(handler)
    for noisy in ("urllib3", "rasterio", "fiona", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class JobLog:
    """Thread-safe bounded log buffer attached to a processing job."""

    def __init__(self, job_id: str, capacity: int = 2000) -> None:
        self.job_id = job_id
        self._buf: Deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._logger = get_logger(f"job.{job_id}")
        self.on_add = None  # optional callback (used to persist logs live)

    def add(self, message: str, level: str = "INFO", **fields) -> None:
        stamp = time.strftime("%H:%M:%S", time.gmtime())
        line = f"[{stamp}] {message}"
        if fields:
            line += " | " + " ".join(f"{k}={v}" for k, v in fields.items())
        with self._lock:
            self._buf.append(line)
        self._logger.log(
            getattr(logging, level.upper(), logging.INFO), message,
            extra={"extra_fields": {"job": self.job_id, **fields}},
        )
        if self.on_add is not None:
            try:
                self.on_add()
            except Exception:  # a persistence hiccup must never break a run
                pass

    def lines(self) -> List[str]:
        with self._lock:
            return list(self._buf)

    def last(self, n: int = 50) -> List[str]:
        with self._lock:
            return list(self._buf)[-n:]


def as_dict(logger_msg: str) -> Dict[str, Optional[str]]:  # pragma: no cover
    return {"message": logger_msg}
