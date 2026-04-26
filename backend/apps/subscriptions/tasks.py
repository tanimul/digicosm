"""
Subscriptions Celery Tasks.

Tasks
-----
process_subscription_renewals    — Auto-renew subscriptions expiring soon (periodic)
expire_grace_period_subscriptions — Expire subs past grace period (periodic)
expire_bundle_subscriptions       — Expire ended bundle subs (periodic)
"""

import logging
from datetime import timedelta

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone

logger = get_task_logger(__name__)


@shared_task(
    name="subscriptions.process_subscription_renewals",
    acks_late=True,
)
def process_subscription_renewals() -> dict:
    """
    Periodic task (run every hour). Auto-renew subscriptions ending within 1 hour.
    """
    from .models import SubscriptionStatus, UserSubscription
    from .services import renew_subscription

    cutoff = timezone.now() + timedelta(hours=1)
    due = UserSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        ends_at__lte=cutoff,
        auto_renew=True,
    ).select_related("user", "plan")

    renewed = 0
    failed = 0
    for sub in due:
        try:
            success = renew_subscription(sub)
            if success:
                renewed += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error("Renewal error for sub %s: %s", sub.id, exc)
            failed += 1

    logger.info("Subscription renewals: %d renewed, %d failed", renewed, failed)
    return {"renewed": renewed, "failed": failed}


@shared_task(
    name="subscriptions.expire_grace_period_subscriptions",
    acks_late=True,
)
def expire_grace_period_subscriptions() -> dict:
    """
    Periodic task. Expire subscriptions that have passed their grace period end.
    """
    from .models import SubscriptionStatus, UserSubscription

    now = timezone.now()
    expired_qs = UserSubscription.objects.filter(
        status=SubscriptionStatus.GRACE,
        grace_ends_at__lt=now,
    )
    count = expired_qs.count()
    for sub in expired_qs:
        sub.expire()

    logger.info("Expired %d grace-period subscriptions", count)
    return {"expired": count}


@shared_task(
    name="subscriptions.expire_ended_subscriptions",
    acks_late=True,
)
def expire_ended_subscriptions() -> dict:
    """
    Periodic task. Expire ACTIVE subscriptions past their ends_at with auto_renew=False.
    """
    from .models import SubscriptionStatus, UserSubscription

    now = timezone.now()
    expired_qs = UserSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        ends_at__lt=now,
        auto_renew=False,
    )
    count = expired_qs.count()
    expired_qs.update(status=SubscriptionStatus.EXPIRED)

    logger.info("Expired %d non-renewing subscriptions", count)
    return {"expired": count}


@shared_task(
    name="subscriptions.expire_bundle_subscriptions",
    acks_late=True,
)
def expire_bundle_subscriptions() -> dict:
    """Periodic task. Expire bundle subscriptions past their ends_at."""
    from .models import BundleSubscription, SubscriptionStatus

    now = timezone.now()
    count = BundleSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        ends_at__lt=now,
        auto_renew=False,
    ).update(status=SubscriptionStatus.EXPIRED)

    logger.info("Expired %d bundle subscriptions", count)
    return {"expired": count}
