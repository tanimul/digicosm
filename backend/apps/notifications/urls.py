"""
Notifications URL Configuration.
All routes are prefixed with /api/v1/notifications/ in the root urls.py.
"""

from django.urls import path

from .views import (
    BulkMarkReadView,
    MarkAllReadView,
    MarkNotificationReadView,
    NotificationListView,
    NotificationPreferenceView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("<uuid:pk>/read/", MarkNotificationReadView.as_view(), name="notification-read"),
    path("mark-all-read/", MarkAllReadView.as_view(), name="mark-all-read"),
    path("bulk-read/", BulkMarkReadView.as_view(), name="bulk-read"),
    path("preferences/", NotificationPreferenceView.as_view(), name="preferences"),
]
