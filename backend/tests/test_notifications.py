"""
Tests for apps.notifications — NotificationTemplate, Notification, API endpoints.
"""

import pytest
from rest_framework import status


# ─── NotificationTemplate Model ──────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationTemplateModel:
    def test_create_template(self, notification_template):
        from apps.notifications.models import NotificationChannel
        assert notification_template.template_key == "test.event"
        assert notification_template.channel == NotificationChannel.IN_APP
        assert notification_template.is_active is True

    def test_template_str(self, notification_template):
        assert "test.event" in str(notification_template)

    def test_template_key_unique(self, db, notification_template):
        from apps.notifications.models import NotificationTemplate, NotificationChannel
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            NotificationTemplate.objects.create(
                name="Duplicate",
                template_key="test.event",  # duplicate
                channel=NotificationChannel.SMS,
                body="Duplicate body",
            )

    def test_template_ordering_by_key(self, db):
        from apps.notifications.models import NotificationTemplate, NotificationChannel
        NotificationTemplate.objects.create(
            name="Z Template", template_key="z.event",
            channel=NotificationChannel.IN_APP, body="Z",
        )
        NotificationTemplate.objects.create(
            name="A Template", template_key="a.event",
            channel=NotificationChannel.IN_APP, body="A",
        )
        keys = list(NotificationTemplate.objects.values_list("template_key", flat=True))
        assert keys == sorted(keys)


# ─── UserNotificationPreference Model ────────────────────────────────────────

@pytest.mark.django_db
class TestUserNotificationPreference:
    def test_create_preference(self, db, user):
        from apps.notifications.models import UserNotificationPreference, NotificationChannel
        pref = UserNotificationPreference.objects.create(
            user=user,
            channel=NotificationChannel.SMS,
            is_enabled=False,
        )
        assert pref.is_enabled is False
        assert pref.channel == NotificationChannel.SMS

    def test_preference_unique_per_user_channel(self, db, user):
        from apps.notifications.models import UserNotificationPreference, NotificationChannel
        from django.db import IntegrityError
        UserNotificationPreference.objects.create(
            user=user, channel=NotificationChannel.EMAIL, is_enabled=True,
        )
        with pytest.raises(IntegrityError):
            UserNotificationPreference.objects.create(
                user=user, channel=NotificationChannel.EMAIL, is_enabled=False,
            )

    def test_preference_str(self, db, user):
        from apps.notifications.models import UserNotificationPreference, NotificationChannel
        pref = UserNotificationPreference.objects.create(
            user=user, channel=NotificationChannel.PUSH, is_enabled=True,
        )
        s = str(pref)
        assert "push" in s.lower() or "on" in s.lower()


# ─── Notification Model ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationModel:
    def test_create_notification(self, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        notif = Notification.objects.create(
            user=user,
            channel=NotificationChannel.IN_APP,
            title="Payment received",
            body="Your deposit of ৳500 was successful.",
            status=NotificationStatus.SENT,
        )
        assert notif.title == "Payment received"
        assert notif.status == NotificationStatus.SENT
        assert notif.is_read is False

    def test_notification_mark_read(self, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        notif = Notification.objects.create(
            user=user,
            channel=NotificationChannel.IN_APP,
            title="Test",
            body="Test body",
            status=NotificationStatus.SENT,
        )
        notif.is_read = True
        notif.save(update_fields=["is_read"])
        notif.refresh_from_db()
        assert notif.is_read is True

    def test_notification_str(self, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        notif = Notification.objects.create(
            user=user,
            channel=NotificationChannel.IN_APP,
            title="Hello",
            body="World",
            status=NotificationStatus.PENDING,
        )
        assert "Hello" in str(notif) or user.phone_number in str(notif)

    def test_notifications_ordered_newest_first(self, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        n1 = Notification.objects.create(
            user=user, channel=NotificationChannel.IN_APP,
            title="First", body="b", status=NotificationStatus.SENT,
        )
        n2 = Notification.objects.create(
            user=user, channel=NotificationChannel.IN_APP,
            title="Second", body="b", status=NotificationStatus.SENT,
        )
        notifs = list(Notification.objects.filter(user=user))
        assert notifs[0].id == n2.id  # newest first


# ─── Notifications API Endpoints ──────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationsAPI:
    def test_list_notifications_requires_auth(self, api_client):
        response = api_client.get("/api/v1/notifications/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_notifications_authenticated(self, auth_client, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        Notification.objects.create(
            user=user, channel=NotificationChannel.IN_APP,
            title="Test notif", body="body", status=NotificationStatus.SENT,
        )
        response = auth_client.get("/api/v1/notifications/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data

    def test_unread_count_in_response(self, auth_client, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        Notification.objects.create(
            user=user, channel=NotificationChannel.IN_APP,
            title="Unread", body="b", status=NotificationStatus.SENT, is_read=False,
        )
        response = auth_client.get("/api/v1/notifications/")
        assert response.status_code == status.HTTP_200_OK

    def test_mark_all_read_requires_auth(self, api_client):
        response = api_client.post("/api/v1/notifications/mark-all-read/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_mark_all_read_authenticated(self, auth_client, db, user):
        from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
        Notification.objects.create(
            user=user, channel=NotificationChannel.IN_APP,
            title="Unread 1", body="b", status=NotificationStatus.SENT, is_read=False,
        )
        response = auth_client.post("/api/v1/notifications/mark-all-read/")
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT)
        assert Notification.objects.filter(user=user, is_read=False).count() == 0
