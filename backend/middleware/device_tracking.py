"""
Device Tracking Middleware — reads the X-Device-ID header and attaches it to the request.

Clients (mobile / web) SHOULD send a stable, locally-generated UUID in
X-Device-ID.  If the header is absent a transient ID is generated for the
request so downstream code always has `request.device_id` available.

The actual persistence of device records is handled by `apps.accounts` via
`UserDevice`; this middleware is purely about propagating the identifier.
"""

import uuid


class DeviceTrackingMiddleware:
    """
    Attaches request.device_id from the X-Device-ID header (or generates one).

    Also echoes the resolved device-id back via the X-Device-ID response header
    so clients that didn't send one can persist it for future requests.
    """

    HEADER = "HTTP_X_DEVICE_ID"
    RESPONSE_HEADER = "X-Device-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.META.get(self.HEADER, "").strip()

        # Basic validation — must be a non-empty string (ideally a UUID)
        if raw and len(raw) <= 64:
            device_id = raw
        else:
            device_id = str(uuid.uuid4())

        request.device_id = device_id

        response = self.get_response(request)
        response[self.RESPONSE_HEADER] = device_id
        return response
