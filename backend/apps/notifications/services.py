"""
Notification Service — creates and dispatches notifications.
"""

import logging
from string import Template

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationTemplate,
    UserNotificationPreference,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def user_channel_enabled(user, channel: str) -> bool:
    """Check if a user has a given notification channel enabled (default: True)."""
    pref = UserNotificationPreference.objects.filter(user=user, channel=channel).first()
    if pref is None:
        return True  # enabled by default
    return pref.is_enabled


def render_template(template: NotificationTemplate, context: dict) -> tuple[str, str]:
    """Render template subject and body with provided context."""
    try:
        title = Template(template.subject).safe_substitute(context)
        body = Template(template.body).safe_substitute(context)
    except Exception as exc:
        logger.warning("Template rendering failed for %s: %s", template.template_key, exc)
        title = template.subject
        body = template.body
    return title, body


def send_notification(
    user,
    template_key: str,
    context: dict | None = None,
    channels: list[str] | None = None,
    metadata: dict | None = None,
) -> list[Notification]:
    """
    Create and queue Notification records for the given user and template.

    Respects user channel preferences. If `channels` is given, only those
    channels are used (still subject to user preferences).

    Dispatches the actual delivery asynchronously via Celery.
    """
    context = context or {}
    metadata = metadata or {}

    templates = NotificationTemplate.objects.filter(
        template_key=template_key, is_active=True
    )
    if channels:
        templates = templates.filter(channel__in=channels)

    created = []
    for tmpl in templates:
        if not user_channel_enabled(user, tmpl.channel):
            continue

        title, body = render_template(tmpl, context)
        notif = Notification.objects.create(
            user=user,
            template=tmpl,
            channel=tmpl.channel,
            title=title,
            body=body,
            status=NotificationStatus.PENDING,
            metadata=metadata,
        )
        created.append(notif)

        # Dispatch async delivery
        try:
            from apps.notifications.tasks import dispatch_notification
            dispatch_notification.delay(str(notif.id))
        except Exception as exc:
            logger.error("Failed to enqueue notification %s: %s", notif.id, exc)

    return created
