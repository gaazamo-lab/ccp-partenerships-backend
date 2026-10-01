"""
Fixed-window rate limiting for unauthenticated public endpoints.

Uses Redis when it is reachable so limits hold across workers; falls back to a
per-process counter (development, tests) — never fails the request because the
limiter itself is unavailable.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from app.core.config import get_settings
from app.core.errors import TooManyRequests

logger = logging.getLogger(__name__)

_local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
_redis = None
_redis_checked = False


def _redis_client():
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    try:
        import redis

        client = redis.Redis.from_url(get_settings().REDIS_URL, socket_connect_timeout=0.2, socket_timeout=0.2)
        client.ping()
        _redis = client
    except Exception:  # noqa: BLE001 — limiter degrades to in-process counting
        logger.info("rate_limit.redis_unavailable using in-process counters")
        _redis = None
    return _redis


def hit(key: str, limit: int, window_seconds: int = 60) -> None:
    window = int(time.time() // window_seconds)
    bucket = f"pcrm:rl:{key}:{window}"
    client = _redis_client()
    count: int
    if client is not None:
        try:
            count = int(client.incr(bucket))
            if count == 1:
                client.expire(bucket, window_seconds + 1)
        except Exception:  # noqa: BLE001
            client = None
    if client is None:
        previous_window, previous_count = _local[key]
        count = previous_count + 1 if previous_window == window else 1
        _local[key] = (window, count)
    if count > limit:
        raise TooManyRequests("Too many attempts. Wait a minute and try again.", retryable=True)


def reset_local() -> None:
    _local.clear()
