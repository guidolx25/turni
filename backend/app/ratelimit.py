"""In-memory login rate limit (spec §7 "simple rate-limit on login").

In-memory is the right size for §11's single container: no Redis, no extra
moving part to operate for five users.

A restart resets every counter BY DESIGN. This is not a bug to fix later: the
limiter exists to blunt online guessing, and an attacker cannot force a restart.
If Turni ever runs more than one process, this needs a shared store — that is the
trigger to revisit, not the restart behaviour.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Counts failures per key over a sliding window.

    Only *failures* are recorded, and a success clears the key, so a user typing
    one wrong password a day never approaches the limit.
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        # Uvicorn runs handlers across a thread pool; the dict must not be
        # mutated from two workers at once.
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        stamps = self._failures[key]
        cutoff = now - self._window_seconds
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()
        if not stamps:
            # Drop empty keys: the IP keyspace is attacker-controlled and this is
            # the only thing keeping the dict from growing without bound.
            del self._failures[key]
        return stamps

    def is_limited(self, key: str, *, now: float | None = None) -> bool:
        at = time.monotonic() if now is None else now
        with self._lock:
            return len(self._prune(key, at)) >= self._max_attempts

    def register_failure(self, key: str, *, now: float | None = None) -> None:
        at = time.monotonic() if now is None else now
        with self._lock:
            self._prune(key, at)
            self._failures[key].append(at)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        """Wipe all counters (test fixtures; nothing in the app calls this)."""
        with self._lock:
            self._failures.clear()
