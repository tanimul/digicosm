"""
Subscriptions App Serializers.
"""

from rest_framework import serializers

from .models import (
    Bundle,
    BundleItem,
    BundleSubscription,
    PlanFeature,
    SubscriptionPlan,
    SubscriptionStatus,
    UserSubscription,
)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


class PlanFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanFeature
        fields = ["id", "feature_key", "feature_label", "feature_value", "is_highlighted", "sort_order"]


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    features = PlanFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id", "name", "slug", "tier", "description", "billing_cycle",
            "price_bdt", "price_credits", "max_concurrent_streams",
            "max_devices", "ai_credits_monthly", "access_level",
            "grace_period_days", "is_highlighted", "sort_order", "features",
        ]


class SubscriptionPlanListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for plan listing (no features inline)."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id", "name", "slug", "tier", "billing_cycle",
            "price_bdt", "price_credits", "is_highlighted", "sort_order",
        ]


# ---------------------------------------------------------------------------
# User Subscription
# ---------------------------------------------------------------------------


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanListSerializer(read_only=True)
    plan_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = UserSubscription
        fields = [
            "id", "plan", "plan_id", "status", "starts_at", "ends_at",
            "grace_ends_at", "auto_renew", "cancelled_at", "cancel_reason",
            "payment_transaction_id", "created_at",
        ]
        read_only_fields = [
            "id", "status", "starts_at", "ends_at", "grace_ends_at",
            "cancelled_at", "payment_transaction_id", "created_at",
        ]


class SubscribePlanSerializer(serializers.Serializer):
    """Input for POST /subscriptions/subscribe/"""
    plan_id = serializers.UUIDField()
    auto_renew = serializers.BooleanField(default=True)


class CancelSubscriptionSerializer(serializers.Serializer):
    cancel_reason = serializers.CharField(max_length=256, required=False, default="")


class ToggleAutoRenewSerializer(serializers.Serializer):
    auto_renew = serializers.BooleanField()


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


class BundleItemSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanListSerializer(read_only=True)

    class Meta:
        model = BundleItem
        fields = ["id", "plan", "note"]


class BundleSerializer(serializers.ModelSerializer):
    items = BundleItemSerializer(many=True, read_only=True)

    class Meta:
        model = Bundle
        fields = [
            "id", "name", "slug", "description", "price_bdt", "price_credits",
            "billing_cycle", "is_featured", "sort_order", "items",
        ]


class SubscribeBundleSerializer(serializers.Serializer):
    bundle_id = serializers.UUIDField()
    auto_renew = serializers.BooleanField(default=True)


class BundleSubscriptionSerializer(serializers.ModelSerializer):
    bundle = BundleSerializer(read_only=True)

    class Meta:
        model = BundleSubscription
        fields = [
            "id", "bundle", "status", "starts_at", "ends_at",
            "auto_renew", "payment_transaction_id", "created_at",
        ]
        read_only_fields = [
            "id", "status", "starts_at", "ends_at",
            "payment_transaction_id", "created_at",
        ]
