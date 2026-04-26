"""
Notifications API Views.

Endpoints
---------
GET    /api/v1/notifications/                     List user's notifications
PATCH  /api/v1/notifications/{id}/read/           Mark single notification read
POST   /api/v1/notifications/mark-all-read/       Mark all in-app notifications read
POST   /api/v1/notifications/bulk-read/           Mark specific notifications read
GET    /api/v1/notifications/preferences/         Get notification preferences
PATCH  /api/v1/notifications/preferences/         Update a channel preference
"""

import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    UserNotificationPreference,
)
from .serializers import (
    BulkMarkReadSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    UpdatePreferenceSerializer,
)

logger = logging.getLogger(__name__)


class NotificationPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListView(generics.ListAPIView):
    """
    GET /notifications/
    List in-app notifications for the authenticated user, newest first.

    Query params: status (pending/sent/read/failed)
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        qs = Notification.objects.filter(
            user=self.request.user,
            channel=NotificationChannel.IN_APP,
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by("-created_at")


class MarkNotificationReadView(APIView):
    """PATCH /notifications/{id}/read/ — mark a single notification as read."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        notif = get_object_or_404(Notification, id=pk, user=request.user)
        notif.mark_read()
        return Response({"success": True, "message": "Marked as read."})


class MarkAllReadView(APIView):
    """POST /notifications/mark-all-read/ — mark all in-app notifications read."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        updated = Notification.objects.filter(
            user=request.user,
            channel=NotificationChannel.IN_APP,
            status=NotificationStatus.SENT,
        ).update(status=NotificationStatus.READ, read_at=timezone.now())
        return Response({"success": True, "marked_read": updated})


class BulkMarkReadView(APIView):
    """POST /notifications/bulk-read/ — mark specific notifications read."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        serializer = BulkMarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["notification_ids"]
        updated = Notification.objects.filter(
            user=request.user,
            id__in=ids,
            channel=NotificationChannel.IN_APP,
        ).update(status=NotificationStatus.READ, read_at=timezone.now())
        return Response({"success": True, "marked_read": updated})


class NotificationPreferenceView(APIView):
    """
    GET  /notifications/preferences/ — list all channel preferences
    PATCH /notifications/preferences/ — update a channel preference
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        prefs = UserNotificationPreference.objects.filter(user=request.user)
        # Return defaults for channels without explicit prefs
        existing = {p.channel: p for p in prefs}
        result = []
        for channel, _ in UserNotificationPreference.channel.field.choices:
            if channel in existing:
                result.append(NotificationPreferenceSerializer(existing[channel]).data)
            else:
                result.append({"channel": channel, "is_enabled": True})
        return Response({"success": True, "data": result})

    def patch(self, request):
        serializer = UpdatePreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        pref, _ = UserNotificationPreference.objects.update_or_create(
            user=request.user,
            channel=data["channel"],
            defaults={"is_enabled": data["is_enabled"]},
        )
        return Response({
            "success": True,
            "data": NotificationPreferenceSerializer(pref).data,
        })
