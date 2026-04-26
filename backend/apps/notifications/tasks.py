"""
Notifications Celery Tasks — async delivery via SMS, push, email, in-app.
"""

import logging

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    name="notifications.dispatch_notification",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def dispatch_notification(self, notification_id: str) -> None:
    """
    Dispatch a single Notification record via its channel.
    Marks sent_at on success, error + status=failed on failure.
    """
    from .models import Notification, NotificationChannel, NotificationStatus

    try:
        notif = Notification.objects.get(id=notification_id)
    except Notification.DoesNotExist:
        logger.warning("Notification %s not found — skipping", notification_id)
        return

    if notif.status not in (NotificationStatus.PENDING,):
        return  # already dispatched

    try:
        if notif.channel == NotificationChannel.IN_APP:
            # In-app notifications are just DB records — mark sent immediately
            pass
        elif notif.channel == NotificationChannel.SMS:
            _send_sms(notif)
        elif notif.channel == NotificationChannel.PUSH:
            _send_push(notif)
        elif notif.channel == NotificationChannel.EMAIL:
            _send_email(notif)

        notif.status = NotificationStatus.SENT
        notif.sent_at = timezone.now()
        notif.save(update_fields=["status", "sent_at"])
        logger.debug("Dispatched notification %s via %s", notification_id, notif.channel)

    except Exception as exc:
        notif.status = NotificationStatus.FAILED
        notif.error = str(exc)
        notif.save(update_fields=["status", "error"])
        logger.error("Failed to dispatch notification %s: %s", notification_id, exc)
        raise self.retry(exc=exc)


def _send_sms(notif) -> None:
    """Send SMS via Bangladesh SMS gateway (configured in settings)."""
    from django.conf import settings
    import requests

    sms_config = getattr(settings, "SMS_GATEWAY", {})
    url = sms_config.get("url", "")
    api_key = sms_config.get("api_key", "")
    sender = sms_config.get("sender_id", "DCE")

    if not url or not api_key:
        logger.warning("SMS gateway not configured — skipping SMS for notification %s", notif.id)
        return

    phone = getattr(notif.user, "phone_number", "")
    if not phone:
        return

    payload = {
        "api_key": api_key,
        "sender_id": sender,
        "message": notif.body,
        "number": phone,
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()


def _send_push(notif) -> None:
    """Send FCM push notification."""
    from django.conf import settings

    fcm_key = getattr(settings, "FCM_SERVER_KEY", "")
    if not fcm_key:
        logger.warning("FCM not configured — skipping push for notification %s", notif.id)
        return

    # Retrieve device tokens from UserDevice model
    from apps.accounts.models import UserDevice
    import requests

    tokens = list(
        UserDevice.objects.filter(user=notif.user, is_active=True)
        .exclude(push_token="")
        .values_list("push_token", flat=True)
    )
    if not tokens:
        return

    headers = {
        "Authorization": f"key={fcm_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "registration_ids": tokens,
        "notification": {
            "title": notif.title,
            "body": notif.body,
        },
        "data": notif.metadata,
    }
    resp = requests.post(
        "https://fcm.googleapis.com/fcm/send",
        json=payload, headers=headers, timeout=10,
    )
    resp.raise_for_status()


def _send_email(notif) -> None:
    """Send email via Django's email backend."""
    from django.core.mail import send_mail
    from django.conf import settings

    email = getattr(notif.user, "email", "")
    if not email:
        return

    send_mail(
        subject=notif.title,
        message=notif.body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


@shared_task(
    name="notifications.cleanup_old_notifications",
    acks_late=True,
)
def cleanup_old_notifications() -> dict:
    """
    Periodic task. Delete read in-app notifications older than 30 days,
    and failed notifications older than 7 days.
    """
    from datetime import timedelta
    from .models import Notification, NotificationChannel, NotificationStatus

    now = timezone.now()

    # Delete old read in-app notifications
    deleted_read, _ = Notification.objects.filter(
        channel=NotificationChannel.IN_APP,
        status=NotificationStatus.READ,
        read_at__lt=now - timedelta(days=30),
    ).delete()

    # Delete old failed notifications
    deleted_failed, _ = Notification.objects.filter(
        status=NotificationStatus.FAILED,
        created_at__lt=now - timedelta(days=7),
    ).delete()

    logger.info(
        "Cleaned up %d read + %d failed notifications",
        deleted_read, deleted_failed,
    )
    return {"deleted_read": deleted_read, "deleted_failed": deleted_failed}
