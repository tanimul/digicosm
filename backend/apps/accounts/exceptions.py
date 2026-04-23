"""
Custom exception handler and HTTP error views for the accounts application.

The custom_exception_handler is registered in REST_FRAMEWORK settings.
The four view functions (bad_request, permission_denied, page_not_found,
server_error) are wired as Django's handler400/403/404/500 in config/urls.py.
"""

import logging

from django.http import JsonResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DRF custom exception handler
# ---------------------------------------------------------------------------


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Wrap DRF's default exception handler to enforce a consistent response
    envelope across all API errors.

    Response shape:
    {
        "success": false,
        "message": "<human-readable summary>",
        "errors": { ... }   // only present when field-level errors exist
    }
    """
    # Delegate to DRF's default handler first
    response: Response | None = exception_handler(exc, context)

    if response is None:
        # Non-DRF exception (e.g. unhandled Python exception): let Django 500
        # handler deal with it; Sentry will capture it via its middleware.
        logger.exception(
            "Unhandled exception in view %s: %s",
            context.get("view"),
            exc,
        )
        return None

    # Normalise the response body
    original_data = response.data

    if isinstance(original_data, list):
        # Top-level list of errors (e.g. non-field ValidationError list)
        errors = {"non_field_errors": original_data}
        message = _summarise(original_data)
    elif isinstance(original_data, dict):
        errors = original_data
        # DRF may put detail at top level or nested
        message = _summarise(original_data)
    else:
        errors = {"detail": str(original_data)}
        message = str(original_data)

    response.data = {
        "success": False,
        "message": message,
        "errors": errors,
    }

    return response


def _summarise(data) -> str:
    """Extract a short human-readable message from the error data."""
    if isinstance(data, list):
        # Take the first item
        first = data[0]
        if hasattr(first, "detail"):
            return str(first.detail)
        return str(first)

    if isinstance(data, dict):
        # "detail" is the DRF standard top-level error key
        if "detail" in data:
            return str(data["detail"])
        # Fall back to the first field's first error message
        for _field, errors in data.items():
            if isinstance(errors, list) and errors:
                first = errors[0]
                if hasattr(first, "message"):
                    return str(first.message)
                return str(first)
            if isinstance(errors, str):
                return errors

    return "An error occurred."


# ---------------------------------------------------------------------------
# Django error views (registered in config/urls.py)
# ---------------------------------------------------------------------------


def bad_request(request, exception=None) -> JsonResponse:
    """HTTP 400 handler."""
    return JsonResponse(
        {"success": False, "message": "Bad request.", "errors": {}},
        status=status.HTTP_400_BAD_REQUEST,
    )


def permission_denied(request, exception=None) -> JsonResponse:
    """HTTP 403 handler."""
    return JsonResponse(
        {"success": False, "message": "Permission denied.", "errors": {}},
        status=status.HTTP_403_FORBIDDEN,
    )


def page_not_found(request, exception=None) -> JsonResponse:
    """HTTP 404 handler."""
    return JsonResponse(
        {
            "success": False,
            "message": "The requested resource was not found.",
            "errors": {},
        },
        status=status.HTTP_404_NOT_FOUND,
    )


def server_error(request) -> JsonResponse:
    """HTTP 500 handler."""
    logger.error("500 Server Error for URL: %s", request.path)
    return JsonResponse(
        {
            "success": False,
            "message": "An internal server error occurred. Our team has been notified.",
            "errors": {},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
