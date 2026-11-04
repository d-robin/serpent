"""Global token-bucket guard.

Protects two things at once: the Pi (from a runaway caller) and the accounts
(from being drained in seconds by a retry loop).  Disabled unless
RATE_LIMIT_PER_MINUTE > 0.
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, per_minute: float, burst: float | None = None):
        self.rate = max(0.0, float(per_minute)) / 60.0
        self.capacity = max(
            1.0, float(burst) if burst and burst > 0 else max(1.0, float(per_minute))
        )
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.rate > 0

    def take(self, amount: float = 1.0) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        if not self.enabled:
            return True, 0.0
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            self._updated = now
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            if self._tokens >= amount:
                self._tokens -= amount
                return True, 0.0
            missing = amount - self._tokens
            return False, round(missing / self.rate, 2)

    def stats(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "per_minute": round(self.rate * 60, 1),
                "capacity": self.capacity,
                "tokens": round(self._tokens, 1),
            }
