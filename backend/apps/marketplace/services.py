"""
Marketplace Service Layer.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    PricingModel,
    Product,
    ProductSubscription,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)


def _subscription_delta(pricing_model: str) -> timedelta:
    if pricing_model == PricingModel.YEARLY:
        return timedelta(days=365)
    return timedelta(days=30)  # monthly default


@transaction.atomic
def purchase_product(user, product: Product, auto_renew: bool = True) -> ProductSubscription:
    """
    Purchase / subscribe to a marketplace product.

    - One-time: creates a subscription that never expires (ends_at far future)
    - Recurring (monthly/yearly): creates a subscription with auto-renew
    - Pay-per-use: creates a subscription with 30-day cycle
    - Free: creates a subscription at no cost

    Raises ValidationError on duplicate active subscription or insufficient funds.
    """
    from apps.wallet.services import WalletService

    # Check duplicate
    existing = ProductSubscription.objects.filter(
        user=user,
        product=product,
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE],
    ).first()
    if existing:
        raise ValidationError(
            f"Already subscribed to {product.name}.",
            code="already_subscribed",
        )

    # Deduct credits (skip for free products)
    txn = None
    if product.pricing_model != PricingModel.FREE and product.price_credits > 0:
        ws = WalletService()
        try:
            from apps.wallet.models import TransactionType
            txn = ws.debit_for_service(
                user=user,
                credits=product.price_credits,
                service_type=TransactionType.MARKETPLACE,
                service_ref={"product_id": str(product.id), "product_name": product.name},
            )
        except Exception as exc:
            raise ValidationError(str(exc), code="payment_failed")

    now = timezone.now()
    if product.pricing_model == PricingModel.ONE_TIME:
        ends_at = now + timedelta(days=36500)  # ~100 years = perpetual
        auto_renew = False
    elif product.pricing_model == PricingModel.FREE:
        ends_at = now + timedelta(days=36500)
        auto_renew = False
    else:
        ends_at = now + _subscription_delta(product.pricing_model)

    sub = ProductSubscription.objects.create(
        user=user,
        product=product,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        ends_at=ends_at,
        auto_renew=auto_renew,
        payment_transaction_id=txn.id if txn else None,
    )

    # Increment purchase count (non-critical)
    from django.db.models import F
    Product.objects.filter(id=product.id).update(
        purchase_count=F("purchase_count") + 1
    )

    logger.info("User %s purchased product %s (sub %s)", user.id, product.name, sub.id)
    return sub
