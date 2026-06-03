"""Async rate and credit helpers used by the Helius client."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Small async leaky-bucket limiter."""

    def __init__(self, rps: float):
        if rps <= 0:
            raise ValueError("rps must be > 0")
        self.min_interval = 1.0 / rps
        self.last = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last = time.monotonic()


class QuotaTracker:
    """In-memory credit counter. Persistence stays in HeliusClient."""

    def __init__(self, max_credits: int, *, label_prefix: str = "credits"):
        if max_credits <= 0:
            raise ValueError("max_credits must be > 0")
        self.max_credits = max_credits
        self.label_prefix = label_prefix
        self._used = 0

    def add(self, n: int) -> None:
        if n < 0:
            raise ValueError("n must be >= 0")
        self._used += n

    def is_exhausted(self) -> bool:
        return self._used >= self.max_credits

    @property
    def used(self) -> int:
        return self._used

    @used.setter
    def used(self, value: int) -> None:
        self._used = max(0, int(value))
