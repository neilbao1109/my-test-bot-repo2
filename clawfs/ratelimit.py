"""In-memory fixed-window rate limiter (per tenant + IP).

Sprint 6 P2. Intentionally process-local and unsuited to multi-replica
deployments — for the demo VM, ClawFS is a single uvicorn process behind
Caddy, so the simple model fits. If we ever shard, swap this for Redis.

Window = 60s. Bucket key = (tenant_id, client_ip). Bounded memory via a
crude LRU eviction at ``MAX_BUCKETS`` entries.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Tuple

WINDOW_SECONDS = 60
MAX_BUCKETS = 10_000


class RateLimiter:
    def __init__(self, window_seconds: int = WINDOW_SECONDS, max_buckets: int = MAX_BUCKETS):
        self._buckets: "OrderedDict[Tuple[str, str], list[float]]" = OrderedDict()
        self._lock = threading.Lock()
        self._window = window_seconds
        self._max = max_buckets

    def check(self, tenant_id: str, ip: str, limit_per_minute: int) -> Tuple[bool, int]:
        """Try to admit a request for (tenant, ip).

        Returns ``(allowed, retry_after_seconds)``. When allowed is True,
        retry_after is 0. When False, retry_after is how many seconds until
        the current 60s window rolls over.
        """
        if limit_per_minute <= 0:
            return True, 0
        now = time.time()
        key = (tenant_id, ip)
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None or now - entry[0] >= self._window:
                # New window.
                self._buckets[key] = [now, 1]
                self._buckets.move_to_end(key)
                self._evict_if_needed()
                return True, 0
            window_start, count = entry
            if count >= limit_per_minute:
                retry = max(1, int(self._window - (now - window_start)) + 1)
                # Touch LRU even on rejection so hot buckets stay resident.
                self._buckets.move_to_end(key)
                return False, retry
            entry[1] = count + 1
            self._buckets.move_to_end(key)
            return True, 0

    def _evict_if_needed(self) -> None:
        while len(self._buckets) > self._max:
            self._buckets.popitem(last=False)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
