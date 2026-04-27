"""
Standardised response helpers for the DCE platform.

All API responses follow the envelope:
    {
        "success": true | false,
        "data":    {...} | [...],   # on success
        "error":   "...",           # on failure
        "errors":  {...},           # field-level validation errors
        "meta":    {...},           # optional metadata (pagination, etc.)
    }
"""

from rest_framework.response import Response


def success_response(data=None, status=200, meta=None):
    """Return a successful envelope response."""
    body = {"success": True}
    if data is not None:
        body["data"] = data
    if meta is not None:
        body["meta"] = meta
    return Response(body, status=status)


def created_response(data=None, meta=None):
    """Shortcut for HTTP 201 Created."""
    return success_response(data=data, status=201, meta=meta)


def error_response(message: str, status=400, errors=None):
    """Return an error envelope response."""
    body = {"success": False, "error": message}
    if errors is not None:
        body["errors"] = errors
    return Response(body, status=status)


def not_found_response(resource: str = "Resource"):
    return error_response(f"{resource} not found.", status=404)


def forbidden_response(message: str = "You do not have permission to perform this action."):
    return error_response(message, status=403)


def validation_error_response(serializer_errors: dict):
    """Convert DRF serializer errors into a standardised 400 response."""
    # Flatten to a single human-readable message for the top-level error key
    first_field = next(iter(serializer_errors))
    first_error = serializer_errors[first_field]
    if isinstance(first_error, list):
        message = f"{first_field}: {first_error[0]}"
    else:
        message = str(first_error)
    return error_response(message, status=400, errors=serializer_errors)


def paginated_response(queryset, serializer_class, request, paginator_class=None):
    """
    Convenience helper: paginate a queryset and return a standard envelope.
    Uses StandardPagination by default.
    """
    from utils.pagination import StandardPagination

    PaginatorClass = paginator_class or StandardPagination
    paginator = PaginatorClass()
    page = paginator.paginate_queryset(queryset, request)
    if page is not None:
        data = serializer_class(page, many=True, context={"request": request}).data
        return paginator.get_paginated_response(data)
    data = serializer_class(queryset, many=True, context={"request": request}).data
    return success_response(data=list(data))
