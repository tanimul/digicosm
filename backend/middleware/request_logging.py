"""
Request Logging Middleware — logs every inbound request and its response status/time.
Skips health-check and static file paths to reduce noise.
"""

import logging
import time
import uuid

logger = logging.getLogger("dce.requests")

SKIP_PREFIXES = ("/health", "/static/", "/media/", "/favicon.ico")


class RequestLoggingMiddleware:
    """
    Attaches a unique request-id to each request, logs method/path/status/duration.

    Headers added to every response:
        X-Request-ID — UUID4 identifying this request (useful for log correlation)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip noisy paths
        if request.path.startswith(SKIP_PREFIXES):
            return self.get_response(request)

        request_id = str(uuid.uuid4())
        request.request_id = request_id
        start = time.monotonic()

        user_id = None
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            user_id = str(request.user.id)

        logger.info(
            "REQUEST  id=%s user=%s method=%s path=%s",
            request_id,
            user_id or "anon",
            request.method,
            request.path,
        )

        response = self.get_response(request)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "RESPONSE id=%s status=%s duration_ms=%s",
            request_id,
            response.status_code,
            duration_ms,
        )

        response["X-Request-ID"] = request_id
        return response
