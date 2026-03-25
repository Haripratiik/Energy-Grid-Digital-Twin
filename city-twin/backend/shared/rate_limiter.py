"""Simple token-bucket rate limiter shared across OpenAI consumers."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket that limits OpenAI API calls per minute."""

    def __init__(self, tokens_per_minute: float = 15, burst: int = 3) -> None:
        self._rate = tokens_per_minute / 60.0  # tokens per second
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def try_acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def wait_and_acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.try_acquire():
                return True
            time.sleep(0.25)
        return False


# Autonomous engine limiter — 2 RPM (leaves headroom for chat)
openai_limiter = TokenBucket(tokens_per_minute=2, burst=1)

# Chat limiter — separate bucket so chat is never starved by auto-analysis
chat_limiter = TokenBucket(tokens_per_minute=2, burst=1)
