"""Tiny in-process response cache.

A repeated identical search costs zero upstream quota, which is the single
biggest quota saver in practice.  Disabled by default (CACHE_TTL_SECONDS=0)
because SERP freshness requirements vary.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

_HOP_BLOCK = {"date", "server", "connection", "transfer-encoding", "content-length"}


@dataclass(frozen=True)
class CachedResponse:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...]
    stored_at: float


class ResponseCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 512):
        self.ttl = max(0.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._data: OrderedDict[str, CachedResponse] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    @staticmethod
    def make_key(method: str, path: str, params: list[tuple[str, str]], body: bytes) -> str:
        h = hashlib.sha256()
        h.update(method.upper().encode())
        h.update(b"\x00")
        h.update(path.encode())
        for key, value in sorted(params):
            h.update(b"\x00")
            h.update(key.encode())
            h.update(b"=")
            h.update(value.encode())
        if body:
            h.update(b"\x00")
            h.update(body)
        return h.hexdigest()

    def get(self, key: str) -> CachedResponse | None:
        if not self.enabled:
            return None
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            if now - item.stored_at > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item

    def put(self, key: str, status_code: int, body: bytes, headers: dict[str, str]) -> None:
        if not self.enabled or status_code != 200:
            return
        kept = tuple(
            (name, value)
            for name, value in headers.items()
            if name.lower() not in _HOP_BLOCK and not name.lower().startswith("x-router-")
        )
        with self._lock:
            self._data[key] = CachedResponse(status_code, body, kept, time.time())
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> int:
        with self._lock:
            n = len(self._data)
            self._data.clear()
            return n

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "enabled": self.enabled,
                "ttl_seconds": self.ttl,
                "entries": len(self._data),
                "capacity": self.max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }
