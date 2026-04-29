"""
Marketplace Celery Tasks.
"""

import logging

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db.models import Avg, Count
from django.utils import timezone

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    name="marketplace.recalculate_product_rating",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def recalculate_product_rating(self, product_id: str) -> None:
    try:
        from .models import Product, ProductReview
        agg = ProductReview.objects.filter(
            product_id=product_id, is_visible=True
        ).aggregate(avg=Avg("stars"), count=Count("id"))
        Product.objects.filter(id=product_id).update(
            avg_rating=round(agg["avg"] or 0, 1),
            rating_count=agg["count"] or 0,
        )
    except Exception as exc:
        logger.error("Failed to recalculate rating for product %s: %s", product_id, exc)
        raise self.retry(exc=exc)


@shared_task(
    name="marketplace.expire_product_subscriptions",
    acks_late=True,
)
def expire_product_subscriptions() -> dict:
    """Periodic task. Expire ended non-renewing product subscriptions."""
    from .models import ProductSubscription, SubscriptionStatus

    count = ProductSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        ends_at__lt=timezone.now(),
        auto_renew=False,
    ).update(status=SubscriptionStatus.EXPIRED)
    logger.info("Expired %d product subscriptions", count)
    return {"expired": count}


@shared_task(
    name="marketplace.renew_product_subscriptions",
    acks_late=True,
)
def renew_product_subscriptions() -> dict:
    """
    Periodic task (hourly). Auto-renew product subscriptions ending within 1 hour.
    """
    from datetime import timedelta
    from .models import ProductSubscription, SubscriptionStatus
    from .services import purchase_product

    cutoff = timezone.now() + timedelta(hours=1)
    due = ProductSubscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        ends_at__lte=cutoff,
        auto_renew=True,
    ).select_related("user", "product")

    renewed = failed = 0
    for sub in due:
        try:
            from apps.wallet.services import WalletService
            from .services import _subscription_delta
            ws = WalletService()
            if sub.product.price_credits > 0:
                txn = ws.deduct_credits(
                    user=sub.user,
                    amount=sub.product.price_credits,
                    description=f"Auto-renewal: {sub.product.name}",
                    reference=f"renew_mkt_{sub.id}",
                )
            now = timezone.now()
            sub.starts_at = now
            sub.ends_at = now + _subscription_delta(sub.product.pricing_model)
            sub.save(update_fields=["starts_at", "ends_at", "updated_at"])
            renewed += 1
        except Exception as exc:
            logger.warning("Product renewal failed for sub %s: %s", sub.id, exc)
            sub.status = SubscriptionStatus.GRACE
            sub.save(update_fields=["status", "updated_at"])
            failed += 1

    return {"renewed": renewed, "failed": failed}
