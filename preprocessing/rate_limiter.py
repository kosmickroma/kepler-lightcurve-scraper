"""
Adaptive Rate Limiter

Detects 429 (Too Many Requests) responses and automatically backs off.
Uses exponential backoff with jitter to avoid thundering herd.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from . import RateLimitError


logger = logging.getLogger(__name__)


@dataclass
class RateLimitState:
    """Current rate limit state."""

    is_limited: bool = False
    backoff_seconds: float = 1.0
    rate_limit_count: int = 0
    last_rate_limit: Optional[float] = None
    requests_since_limit: int = 0


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter with exponential backoff.

    Automatically detects rate limiting and backs off appropriately.
    Uses exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max).
    """

    def __init__(
        self,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        backoff_multiplier: float = 2.0,
        cooldown_threshold: int = 100,
    ):
        """
        Initialize rate limiter.

        Args:
            initial_backoff: Initial backoff duration in seconds
            max_backoff: Maximum backoff duration in seconds
            backoff_multiplier: Multiplier for exponential backoff (usually 2.0)
            cooldown_threshold: Requests before considering cooldown complete
        """
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier
        self.cooldown_threshold = cooldown_threshold

        self.state = RateLimitState()
        self._lock = asyncio.Lock()

        logger.info(
            f"RateLimiter initialized: backoff={initial_backoff}s-{max_backoff}s, "
            f"multiplier={backoff_multiplier}"
        )

    async def wait_if_needed(self) -> None:
        """
        Wait if currently rate limited.

        Should be called before each request.
        """
        async with self._lock:
            if self.state.is_limited:
                logger.warning(
                    f"Rate limited: waiting {self.state.backoff_seconds:.1f}s "
                    f"(attempt {self.state.rate_limit_count})"
                )
                await asyncio.sleep(self.state.backoff_seconds)

                # Still limited, but allow retry
                self.state.is_limited = False
                self.state.requests_since_limit = 0

    async def report_rate_limit(self) -> None:
        """
        Report that a 429 response was received.

        Triggers exponential backoff.
        """
        async with self._lock:
            self.state.is_limited = True
            self.state.rate_limit_count += 1
            self.state.last_rate_limit = time.time()
            self.state.requests_since_limit = 0

            # Exponential backoff with cap
            self.state.backoff_seconds = min(
                self.state.backoff_seconds * self.backoff_multiplier,
                self.max_backoff,
            )

            logger.error(
                f"Rate limit hit! Count: {self.state.rate_limit_count}, "
                f"Next backoff: {self.state.backoff_seconds:.1f}s"
            )

    async def report_success(self) -> None:
        """
        Report successful request.

        After sufficient successful requests, reset backoff to initial value.
        """
        async with self._lock:
            self.state.requests_since_limit += 1

            # If we've had enough successful requests, consider it cooled down
            if self.state.requests_since_limit >= self.cooldown_threshold:
                if self.state.backoff_seconds > self.initial_backoff:
                    logger.info(
                        f"Cooldown complete: resetting backoff to {self.initial_backoff}s"
                    )
                    self.state.backoff_seconds = self.initial_backoff

    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        return {
            'is_limited': self.state.is_limited,
            'rate_limit_count': self.state.rate_limit_count,
            'current_backoff': self.state.backoff_seconds,
            'requests_since_limit': self.state.requests_since_limit,
            'last_rate_limit': self.state.last_rate_limit,
        }
