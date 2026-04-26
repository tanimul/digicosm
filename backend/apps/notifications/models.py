"""
Notifications App Models — DCE Platform.

Models
------
NotificationTemplate        — Reusable templates for each notification type/channel
UserNotificationPreference  — Per-user, per-channel opt-in/out settings
Notification                — An individual notification sent (or queued) for a user
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


class NotificationChannel(models.TextChoices):
    IN_APP = "in_app", _("In-App")
    SMS    = "sms",    _("SMS")
    PUSH   = "push",   _("Push Notification (FCM/APNs)")
    EMAIL  = "email",  _("Email")


class NotificationStatus(models.TextChoices):
    PENDING  = "pending",  _("Pending")
    SENT     = "sent",     _("Sent")
    FAILED   = "failed",   _("Failed")
    READ     = "read",     _("Read")


# ---------------------------------------------------------------------------
# NotificationTemplate
# ---------------------------------------------------------------------------


class NotificationTemplate(models.Model):
    """
    Reusable notification template for a specific event type and channel.

    Subject/body support Django template syntax with context variables.
    e.g., "Hello {{ user.first_name }}, your payment of {{ amount }} BDT was received."
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=128, unique=True)
    template_key = models.CharField(
                       max_length=64, unique=True, db_index=True,
                       help_text=_("Code key used to look up template, e.g. 'wallet.deposit_success'"),
                   )
    channel      = models.CharField(
                       max_length=10,
                       choices=NotificationChannel.choices,
                       db_index=True,
                   )
    subject      = models.CharField(
                       max_length=256, blank=True, default="",
                       help_text=_("Email subject or push notification title"),
                   )
    body         = models.TextField(
                       help_text=_("Notification body — supports Django template variables"),
                   )
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Notification Template")
        verbose_name_plural = _("Notification Templates")
        ordering            = ["template_key"]

    def __str__(self) -> str:
        return f"{self.template_key} ({self.channel})"


# ---------------------------------------------------------------------------
# UserNotificationPreference
# ---------------------------------------------------------------------------


class UserNotificationPreference(models.Model):
    """Per-user opt-in/out for each notification channel."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
                     User,
                     on_delete=models.CASCADE,
                     related_name="notification_preferences",
                 )
    channel    = models.CharField(
                     max_length=10,
                     choices=NotificationChannel.choices,
                 )
    is_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Notification Preference")
        verbose_name_plural = _("Notification Preferences")
        unique_together     = [("user", "channel")]

    def __str__(self) -> str:
        state = "on" if self.is_enabled else "off"
        return f"{self.user} — {self.channel}: {state}"


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


class Notification(models.Model):
    """
    An individual notification record — one per user per channel per event.

    Created by the notification service and dispatched by Celery tasks.
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
                      User,
                      on_delete=models.CASCADE,
                      related_name="notifications",
                  )
    template    = models.ForeignKey(
                      NotificationTemplate,
                      on_delete=models.SET_NULL,
                      null=True, blank=True,
                      related_name="notifications",
                  )
    channel     = models.CharField(
                      max_length=10,
                      choices=NotificationChannel.choices,
                      db_index=True,
                  )

    # Rendered content (template is rendered at send time)
    title       = models.CharField(max_length=256, blank=True, default="")
    body        = models.TextField()

    # Delivery
    status      = models.CharField(
                      max_length=10,
                      choices=NotificationStatus.choices,
                      default=NotificationStatus.PENDING,
                      db_index=True,
                  )
    sent_at     = models.DateTimeField(null=True, blank=True)
    read_at     = models.DateTimeField(null=True, blank=True)
    error       = models.TextField(
                      blank=True, default="",
                      help_text=_("Error message if delivery failed"),
                  )

    # Additional context (e.g., linked entity IDs for deep-links)
    metadata    = models.JSONField(default=dict, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name        = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Notification({self.user_id}, {self.channel}, {self.status})"

    def mark_read(self) -> None:
        from django.utils import timezone
        self.status = NotificationStatus.READ
        self.read_at = timezone.now()
        self.save(update_fields=["status", "read_at"])
