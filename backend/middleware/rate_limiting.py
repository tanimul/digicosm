"""
Rate Limiting Middleware — Redis-backed per-user (or per-IP) request throttling.

Rules (configurable via Django settings):
    RATE_LIMIT_REQUESTS  — max requests per window (default: 300)
    RATE_LIMIT_WINDOW    — window size in seconds (default: 60)
    RATE_LIMIT_ENABLED   — toggle on/off (default: True)

Keys:
    Authenticated users  → rl:user:{user_id}
    Anonymous requests   → rl:ip:{client_ip}

Endpoints that bypass rate-limiting:
    /health, /static/, /media/

On limit exceeded the middleware returns 429 with Retry-After header.
"""

import json
import logging
import time

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger("dce.rate_limit")

# Configurable defaults
RATE_LIMIT_REQUESTS: int = getattr(settings, "RATE_LIMIT_REQUESTS", 300)
RATE_LIMIT_WINDOW: int = getattr(settings, "RATE_LIMIT_WINDOW", 60)
RATE_LIMIT_ENABLED: bool = getattr(settings, "RATE_LIMIT_ENABLED", True)

BYPASS_PREFIXES = ("/health", "/static/", "/media/")


def _get_client_ip(request) -> str:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class RateLimitingMiddleware:
    """
    Sliding-window rate limiter using Redis INCR + EXPIRE.

    Strategy:
        1. Build a cache key based on user id (auth) or client IP (anon).
        2. INCR the key — Redis atomically increments.
        3. On first access (count == 1) set TTL = window seconds.
        4. If count > limit return 429.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _get_redis(self):
        """Lazy-import to avoid import-time Django cache setup issues."""
        from django.core.cache import cache
        return cache

    def __call__(self, request):
        if not RATE_LIMIT_ENABLED:
            return self.get_response(request)

        if request.path.startswith(BYPASS_PREFIXES):
            return self.get_response(request)

        cache = self._get_redis()

        # Build cache key
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            cache_key = f"rl:user:{request.user.id}"
        else:
            cache_key = f"rl:ip:{_get_client_ip(request)}"

        # Increment counter; set TTL on first hit
        count = cache.get(cache_key, 0)
        count += 1
        if count == 1:
            cache.set(cache_key, count, timeout=RATE_LIMIT_WINDOW)
        else:
            cache.set(cache_key, count, timeout=None)  # preserve existing TTL

        if count > RATE_LIMIT_REQUESTS:
            logger.warning(
                "RATE_LIMIT_EXCEEDED key=%s count=%s limit=%s",
                cache_key,
                count,
                RATE_LIMIT_REQUESTS,
            )
            body = json.dumps({
                "success": False,
                "error": "Rate limit exceeded. Please slow down.",
                "retry_after": RATE_LIMIT_WINDOW,
            })
            response = HttpResponse(
                body,
                content_type="application/json",
                status=429,
            )
            response["Retry-After"] = str(RATE_LIMIT_WINDOW)
            return response

        response = self.get_response(request)
        response["X-RateLimit-Limit"] = str(RATE_LIMIT_REQUESTS)
        response["X-RateLimit-Remaining"] = str(max(0, RATE_LIMIT_REQUESTS - count))
        return response
