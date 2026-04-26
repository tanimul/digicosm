"""
Notifications App Serializers.
"""

from rest_framework import serializers

from .models import Notification, NotificationTemplate, UserNotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id", "channel", "title", "body", "status",
            "sent_at", "read_at", "metadata", "created_at",
        ]
        read_only_fields = [f.name for f in Notification._meta.fields]


class MarkReadSerializer(serializers.Serializer):
    """Body for PATCH /notifications/{id}/read/"""
    pass  # no body required — just the action


class BulkMarkReadSerializer(serializers.Serializer):
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotificationPreference
        fields = ["id", "channel", "is_enabled"]
        read_only_fields = ["id"]


class UpdatePreferenceSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=[
        ("in_app", "In-App"),
        ("sms", "SMS"),
        ("push", "Push Notification (FCM/APNs)"),
        ("email", "Email"),
    ])
    is_enabled = serializers.BooleanField()


class NotificationTemplateSerializer(serializers.ModelSerializer):
    """Admin-facing template serializer."""
    class Meta:
        model = NotificationTemplate
        fields = [
            "id", "name", "template_key", "channel",
            "subject", "body", "is_active", "created_at",
        ]
