"""
Subscriptions Service Layer — business logic for subscribing, renewing, cancelling.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    Bundle,
    BundleSubscription,
    SubscriptionPlan,
    SubscriptionStatus,
    UserSubscription,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _billing_cycle_delta(billing_cycle: str) -> timedelta:
    if billing_cycle == "yearly":
        return timedelta(days=365)
    if billing_cycle == "quarterly":
        return timedelta(days=90)
    return timedelta(days=30)  # monthly default


@transaction.atomic
def subscribe_to_plan(user, plan: SubscriptionPlan, auto_renew: bool = True) -> UserSubscription:
    """
    Subscribe a user to a plan. Deducts credits from wallet.

    Raises ValidationError if:
    - User already has an active subscription to same plan
    - Insufficient wallet credits
    """
    from apps.wallet.models import Wallet
    from apps.wallet.services import WalletService

    # Check for duplicate active subscription
    existing = UserSubscription.objects.filter(
        user=user,
        plan=plan,
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE],
    ).first()
    if existing:
        raise ValidationError(
            f"Already have an active {plan.name} subscription.",
            code="already_subscribed",
        )

    # Deduct credits
    ws = WalletService()
    try:
        from apps.wallet.models import TransactionType
        txn = ws.debit_for_service(
            user=user,
            credits=plan.price_credits,
            service_type=TransactionType.SUBSCRIPTION,
            service_ref={"plan_id": str(plan.id), "plan_name": plan.name},
        )
    except Exception as exc:
        raise ValidationError(str(exc), code="payment_failed")

    now = timezone.now()
    ends_at = now + _billing_cycle_delta(plan.billing_cycle)

    sub = UserSubscription.objects.create(
        user=user,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        ends_at=ends_at,
        auto_renew=auto_renew,
        renewal_credits_charged=plan.price_credits,
        payment_transaction_id=txn.id if txn else None,
    )
    logger.info("User %s subscribed to plan %s (ends %s)", user.id, plan.name, ends_at.date())
    return sub


@transaction.atomic
def renew_subscription(subscription: UserSubscription) -> bool:
    """
    Auto-renew a subscription. Returns True on success, False on failure.
    Called by the periodic renewal Celery task.
    """
    from apps.wallet.services import WalletService

    ws = WalletService()
    plan = subscription.plan
    try:
        from apps.wallet.models import TransactionType
        txn = ws.debit_for_service(
            user=subscription.user,
            credits=plan.price_credits,
            service_type=TransactionType.SUBSCRIPTION,
            service_ref={"plan_id": str(plan.id), "renewal": True, "sub_id": str(subscription.id)},
        )
    except Exception as exc:
        logger.warning(
            "Auto-renewal failed for sub %s: %s — entering grace period",
            subscription.id, exc,
        )
        subscription.enter_grace()
        return False

    now = timezone.now()
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.starts_at = now
    subscription.ends_at = now + _billing_cycle_delta(plan.billing_cycle)
    subscription.renewal_credits_charged = plan.price_credits
    subscription.payment_transaction_id = txn.id if txn else None
    subscription.grace_ends_at = None
    subscription.save(update_fields=[
        "status", "starts_at", "ends_at", "renewal_credits_charged",
        "payment_transaction_id", "grace_ends_at", "updated_at",
    ])
    logger.info("Renewed subscription %s for user %s", subscription.id, subscription.user_id)
    return True


@transaction.atomic
def subscribe_to_bundle(user, bundle: Bundle, auto_renew: bool = True) -> BundleSubscription:
    """Subscribe a user to a bundle. Deducts credits from wallet."""
    from apps.wallet.services import WalletService

    existing = BundleSubscription.objects.filter(
        user=user,
        bundle=bundle,
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE],
    ).first()
    if existing:
        raise ValidationError(
            f"Already subscribed to bundle {bundle.name}.",
            code="already_subscribed",
        )

    ws = WalletService()
    try:
        from apps.wallet.models import TransactionType
        txn = ws.debit_for_service(
            user=user,
            credits=bundle.price_credits,
            service_type=TransactionType.SUBSCRIPTION,
            service_ref={"bundle_id": str(bundle.id), "bundle_name": bundle.name},
        )
    except Exception as exc:
        raise ValidationError(str(exc), code="payment_failed")

    now = timezone.now()
    ends_at = now + _billing_cycle_delta(bundle.billing_cycle)

    sub = BundleSubscription.objects.create(
        user=user,
        bundle=bundle,
        status=SubscriptionStatus.ACTIVE,
        starts_at=now,
        ends_at=ends_at,
        auto_renew=auto_renew,
        payment_transaction_id=txn.id if txn else None,
    )
    logger.info("User %s subscribed to bundle %s", user.id, bundle.name)
    return sub
