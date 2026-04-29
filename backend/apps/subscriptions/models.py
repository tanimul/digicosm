"""
Subscriptions App Models — DCE Platform.

Models
------
SubscriptionPlan       — Starter / Growth / Pro tier definitions
PlanFeature            — Feature bullet points for each plan
UserSubscription       — A user's active or past subscription
Bundle                 — Pre-packaged combinations of plans/services
BundleItem             — Individual plan/service included in a bundle
BundleSubscription     — A user's bundle subscription record
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


class PlanTier(models.TextChoices):
    STARTER = "starter", _("Starter")
    GROWTH  = "growth",  _("Growth")
    PRO     = "pro",     _("Pro")


class BillingCycle(models.TextChoices):
    MONTHLY  = "monthly",  _("Monthly")
    QUARTERLY = "quarterly", _("Quarterly (3 months)")
    YEARLY   = "yearly",   _("Yearly")


class SubscriptionStatus(models.TextChoices):
    ACTIVE    = "active",    _("Active")
    GRACE     = "grace",     _("Grace Period")
    EXPIRED   = "expired",   _("Expired")
    CANCELLED = "cancelled", _("Cancelled")
    PAUSED    = "paused",    _("Paused")


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------


class SubscriptionPlan(models.Model):
    """
    Defines a subscription tier (Starter, Growth, Pro).

    Prices are stored in both BDT and platform credits for flexibility.
    access_level maps to streaming.AccessLevel choices.
    """

    id                    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name                  = models.CharField(max_length=64, unique=True)
    slug                  = models.SlugField(max_length=64, unique=True, db_index=True)
    tier                  = models.CharField(
                                max_length=10, choices=PlanTier.choices,
                                unique=True, db_index=True,
                            )
    description           = models.TextField(blank=True, default="")
    billing_cycle         = models.CharField(
                                max_length=12,
                                choices=BillingCycle.choices,
                                default=BillingCycle.MONTHLY,
                            )

    # Pricing
    price_bdt             = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    price_credits         = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    # Limits
    max_concurrent_streams = models.PositiveSmallIntegerField(
                                 default=2,
                                 help_text=_("Max simultaneous streams for this plan"),
                             )
    max_devices           = models.PositiveSmallIntegerField(default=3)
    ai_credits_monthly    = models.DecimalField(
                                max_digits=12, decimal_places=2, default=Decimal("0"),
                                help_text=_("Monthly AI credits included in plan"),
                            )

    # Access level used by streaming access control
    access_level          = models.CharField(
                                max_length=10, default="starter",
                                help_text=_("Maps to streaming AccessLevel: starter/growth/pro"),
                            )

    # Grace period (days after expiry before suspension)
    grace_period_days     = models.PositiveSmallIntegerField(default=3)

    is_active             = models.BooleanField(default=True, db_index=True)
    is_highlighted        = models.BooleanField(
                                default=False,
                                help_text=_("Show as recommended/popular plan in UI"),
                            )
    sort_order            = models.PositiveIntegerField(default=0)
    created_at            = models.DateTimeField(auto_now_add=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Subscription Plan")
        verbose_name_plural = _("Subscription Plans")
        ordering            = ["sort_order", "price_bdt"]

    def __str__(self) -> str:
        return f"{self.name} ({self.billing_cycle})"


# ---------------------------------------------------------------------------
# PlanFeature
# ---------------------------------------------------------------------------


class PlanFeature(models.Model):
    """Feature line items displayed on the pricing/plan page for a given plan."""

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan          = models.ForeignKey(
                        SubscriptionPlan,
                        on_delete=models.CASCADE,
                        related_name="features",
                    )
    feature_key   = models.CharField(max_length=64)
    feature_label = models.CharField(max_length=256)
    feature_value = models.CharField(max_length=128, blank=True, default="")
    is_highlighted = models.BooleanField(
                         default=False,
                         help_text=_("Bold/highlight this feature in the UI"),
                     )
    sort_order    = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name        = _("Plan Feature")
        verbose_name_plural = _("Plan Features")
        ordering            = ["plan", "sort_order"]
        unique_together     = [("plan", "feature_key")]

    def __str__(self) -> str:
        return f"{self.plan.name}: {self.feature_label}"


# ---------------------------------------------------------------------------
# UserSubscription
# ---------------------------------------------------------------------------


class UserSubscription(models.Model):
    """
    Records a user's subscription to a SubscriptionPlan.

    Lifecycle:
      ACTIVE → (end of cycle) → GRACE (if auto-renew fails) → EXPIRED
      ACTIVE → CANCELLED (user cancels) → EXPIRED at cycle end
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
                      User,
                      on_delete=models.CASCADE,
                      related_name="subscriptions",
                  )
    plan        = models.ForeignKey(
                      SubscriptionPlan,
                      on_delete=models.PROTECT,
                      related_name="user_subscriptions",
                  )
    status      = models.CharField(
                      max_length=12,
                      choices=SubscriptionStatus.choices,
                      default=SubscriptionStatus.ACTIVE,
                      db_index=True,
                  )

    # Billing period
    starts_at   = models.DateTimeField()
    ends_at     = models.DateTimeField(db_index=True)
    grace_ends_at = models.DateTimeField(
                        null=True, blank=True,
                        help_text=_("Grace period end (set when status → grace)"),
                    )

    # Renewal
    auto_renew  = models.BooleanField(default=True)
    renewal_credits_charged = models.DecimalField(
                                  max_digits=12, decimal_places=2, default=Decimal("0"),
                                  help_text=_("Credits deducted for last renewal"),
                              )

    # Cancellation
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=256, blank=True, default="")

    # Reference to wallet transaction for audit
    payment_transaction_id = models.UUIDField(null=True, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("User Subscription")
        verbose_name_plural = _("User Subscriptions")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "ends_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.plan.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE)

    def cancel(self, reason: str = "") -> None:
        self.status = SubscriptionStatus.CANCELLED
        self.auto_renew = False
        self.cancelled_at = timezone.now()
        self.cancel_reason = reason
        self.save(update_fields=["status", "auto_renew", "cancelled_at", "cancel_reason", "updated_at"])

    def enter_grace(self) -> None:
        from datetime import timedelta
        self.status = SubscriptionStatus.GRACE
        self.grace_ends_at = timezone.now() + timedelta(days=self.plan.grace_period_days)
        self.save(update_fields=["status", "grace_ends_at", "updated_at"])

    def expire(self) -> None:
        self.status = SubscriptionStatus.EXPIRED
        self.save(update_fields=["status", "updated_at"])


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


class Bundle(models.Model):
    """
    A pre-packaged combination of subscription plans and/or services
    offered at a discounted combined price.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=128, unique=True)
    slug         = models.SlugField(max_length=128, unique=True, db_index=True)
    description  = models.TextField(blank=True, default="")
    plans        = models.ManyToManyField(
                       SubscriptionPlan,
                       through="BundleItem",
                       related_name="bundles",
                       blank=True,
                   )
    price_bdt    = models.DecimalField(max_digits=10, decimal_places=2)
    price_credits = models.DecimalField(max_digits=12, decimal_places=2)
    billing_cycle = models.CharField(
                        max_length=12,
                        choices=BillingCycle.choices,
                        default=BillingCycle.MONTHLY,
                    )
    is_active    = models.BooleanField(default=True, db_index=True)
    is_featured  = models.BooleanField(default=False)
    sort_order   = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Bundle")
        verbose_name_plural = _("Bundles")
        ordering            = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class BundleItem(models.Model):
    """Through model: which plans are included in a bundle."""

    id     = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="items")
    plan   = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE)
    note   = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        unique_together = [("bundle", "plan")]
        verbose_name        = _("Bundle Item")
        verbose_name_plural = _("Bundle Items")

    def __str__(self) -> str:
        return f"{self.bundle.name} → {self.plan.name}"


# ---------------------------------------------------------------------------
# BundleSubscription
# ---------------------------------------------------------------------------


class BundleSubscription(models.Model):
    """A user's active subscription to a Bundle."""

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
                      User,
                      on_delete=models.CASCADE,
                      related_name="bundle_subscriptions",
                  )
    bundle      = models.ForeignKey(
                      Bundle,
                      on_delete=models.PROTECT,
                      related_name="subscriptions",
                  )
    status      = models.CharField(
                      max_length=12,
                      choices=SubscriptionStatus.choices,
                      default=SubscriptionStatus.ACTIVE,
                      db_index=True,
                  )
    starts_at   = models.DateTimeField()
    ends_at     = models.DateTimeField(db_index=True)
    auto_renew  = models.BooleanField(default=True)
    payment_transaction_id = models.UUIDField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Bundle Subscription")
        verbose_name_plural = _("Bundle Subscriptions")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "ends_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.bundle.name} ({self.status})"
