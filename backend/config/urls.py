"""
Root URL configuration for the Digital Consumption Ecosystem Platform.

All public APIs are versioned under /api/v1/.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView

# ---------------------------------------------------------------------------
# Health-check endpoint (no auth required, used by load-balancer probes)
# ---------------------------------------------------------------------------


def health_check(request):
    """Simple liveness probe."""
    return JsonResponse({"status": "ok", "service": "dce-backend"})


def ready_check(request):
    """Readiness probe — verifies DB and cache connectivity."""
    from django.db import connection

    checks: dict = {}
    overall = "ok"

    # Database
    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"
        overall = "degraded"

    # Cache
    try:
        from django.core.cache import cache

        cache.set("readiness_probe", "1", timeout=5)
        assert cache.get("readiness_probe") == "1"
        checks["cache"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["cache"] = f"error: {exc}"
        overall = "degraded"

    status_code = 200 if overall == "ok" else 503
    return JsonResponse({"status": overall, "checks": checks}, status=status_code)


# ---------------------------------------------------------------------------
# API v1 URL patterns
# ---------------------------------------------------------------------------

api_v1_patterns = [
    # Accounts / Auth
    path("auth/", include("apps.accounts.urls", namespace="accounts")),
    # Wallet & Payments
    path("wallet/", include("apps.wallet.urls", namespace="wallet")),
    # AI Gateway (content recommendations, chatbot, etc.)
    path("ai/", include("apps.ai_gateway.urls", namespace="ai_gateway")),
    # Streaming (video/audio content)
    path("streaming/", include("apps.streaming.urls", namespace="streaming")),
    # Marketplace (digital products)
    path("marketplace/", include("apps.marketplace.urls", namespace="marketplace")),
    # Subscriptions
    path("subscriptions/", include("apps.subscriptions.urls", namespace="subscriptions")),
    # Notifications
    path("notifications/", include("apps.notifications.urls", namespace="notifications")),
    # Admin panel (custom management APIs — separate from Django admin)
    path("admin-panel/", include("apps.admin_panel.urls", namespace="admin_panel")),
]

# ---------------------------------------------------------------------------
# Root URL patterns
# ---------------------------------------------------------------------------

urlpatterns = [
    # Django admin
    path("django-admin/", admin.site.urls),
    # API versioning
    path("api/v1/", include((api_v1_patterns, "v1"))),
    # Probe endpoints (no auth, no rate limiting)
    path("health/", health_check, name="health_check"),
    path("ready/", ready_check, name="ready_check"),
    # Redirect bare root to API docs (or remove if not serving docs)
    path("", RedirectView.as_view(url="/api/v1/", permanent=False), name="root"),
]

# ---------------------------------------------------------------------------
# Debug-only additions
# ---------------------------------------------------------------------------

if settings.DEBUG:
    # Serve media files via Django's dev server
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Django Debug Toolbar
    try:
        import debug_toolbar  # noqa: F401

        urlpatterns = [
            path("__debug__/", include("debug_toolbar.urls")),
        ] + urlpatterns
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Custom error handlers
# ---------------------------------------------------------------------------

handler400 = "apps.accounts.exceptions.bad_request"
handler403 = "apps.accounts.exceptions.permission_denied"
handler404 = "apps.accounts.exceptions.page_not_found"
handler500 = "apps.accounts.exceptions.server_error"
