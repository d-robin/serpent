"""Structured logging plus a tiny counter set for /metrics."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import Counter


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "path", "status", "account", "latency_ms", "attempt", "client"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def setup_logging(level: str = "info", *, json_logs: bool = True) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # uvicorn's own access log duplicates ours
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class Counters:
    """Process-lifetime counters, cheap enough for a Pi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self.started_at = time.time()

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def get(self, name: str) -> int:
        with self._lock:
            return self._counters[name]

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)
