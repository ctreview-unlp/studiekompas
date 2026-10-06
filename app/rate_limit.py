"""
Minimal in-memory rate limiter for the public chat endpoint.

Every /api/chat call costs real money (a Claude request with the full course
list), and the endpoint is reachable by anyone who can load unlp.nl. This
caps how many messages a single client can send in a sliding time window.

In-memory is deliberate for the MVP: one Railway instance, no extra
infrastructure. Limits reset on redeploy, and if the app is ever scaled to
multiple instances each one counts separately — move this to Postgres or
Redis at that point.
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        # FastAPI runs sync endpoints in a threadpool, so guard shared state.
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for `key` and return False if it exceeds the limit."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            # Drop idle keys so the dict doesn't grow forever.
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                    del self._hits[k]
            return True
