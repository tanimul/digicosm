"""
Tests for apps.subscriptions — SubscriptionPlan, UserSubscription, API endpoints.
"""

from decimal import Decimal

import pytest
from rest_framework import status


# ─── SubscriptionPlan Model ───────────────────────────────────────────────────

@pytest.mark.django_db
class TestSubscriptionPlanModel:
    def test_create_plan(self, subscription_plan):
        from apps.subscriptions.models import PlanTier, BillingCycle
        assert subscription_plan.name == "Starter Monthly"
        assert subscription_plan.tier == PlanTier.STARTER
        assert subscription_plan.billing_cycle == BillingCycle.MONTHLY
        assert subscription_plan.price_bdt == Decimal("299.00")
        assert subscription_plan.is_active is True

    def test_plan_str(self, subscription_plan):
        assert "Starter" in str(subscription_plan)

    def test_plan_slug_unique(self, db, subscription_plan):
        from apps.subscriptions.models import SubscriptionPlan, PlanTier, BillingCycle
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            SubscriptionPlan.objects.create(
                name="Another Starter",
                slug="starter-monthly",  # duplicate
                tier=PlanTier.GROWTH,
                billing_cycle=BillingCycle.MONTHLY,
                price_bdt="499.00",
            )

    def test_tier_unique(self, db, subscription_plan):
        from apps.subscriptions.models import SubscriptionPlan, PlanTier, BillingCycle
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            SubscriptionPlan.objects.create(
                name="Starter Yearly",
                slug="starter-yearly-dup",
                tier=PlanTier.STARTER,  # duplicate tier
                billing_cycle=BillingCycle.YEARLY,
                price_bdt="2999.00",
            )

    def test_ordering_by_price(self, db):
        from apps.subscriptions.models import SubscriptionPlan, PlanTier, BillingCycle
        SubscriptionPlan.objects.all().delete()
        p2 = SubscriptionPlan.objects.create(
            name="Growth M", slug="growth-m",
            tier=PlanTier.GROWTH, billing_cycle=BillingCycle.MONTHLY,
            price_bdt="499.00",
        )
        p1 = SubscriptionPlan.objects.create(
            name="Starter M", slug="starter-m",
            tier=PlanTier.STARTER, billing_cycle=BillingCycle.MONTHLY,
            price_bdt="299.00",
        )
        plans = list(SubscriptionPlan.objects.all())
        assert plans[0].price_bdt <= plans[1].price_bdt


# ─── UserSubscription Model ───────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserSubscription:
    def test_create_subscription(self, db, user, subscription_plan):
        from apps.subscriptions.models import UserSubscription, SubscriptionStatus
        from django.utils import timezone
        from datetime import timedelta
        sub = UserSubscription.objects.create(
            user=user,
            plan=subscription_plan,
            status=SubscriptionStatus.ACTIVE,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
        )
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.user == user

    def test_subscription_str(self, db, user, subscription_plan):
        from apps.subscriptions.models import UserSubscription, SubscriptionStatus
        from django.utils import timezone
        from datetime import timedelta
        sub = UserSubscription.objects.create(
            user=user,
            plan=subscription_plan,
            status=SubscriptionStatus.ACTIVE,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=30),
        )
        assert user.phone_number in str(sub) or "Starter" in str(sub)


# ─── Subscriptions API Endpoints ──────────────────────────────────────────────

@pytest.mark.django_db
class TestSubscriptionsAPI:
    def test_list_plans_requires_auth(self, api_client):
        response = api_client.get("/api/v1/subscriptions/plans/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_plans_authenticated(self, auth_client, subscription_plan):
        response = auth_client.get("/api/v1/subscriptions/plans/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data
        assert len(data["results"]) >= 1

    def test_my_subscriptions_empty(self, auth_client):
        response = auth_client.get("/api/v1/subscriptions/my/")
        assert response.status_code == status.HTTP_200_OK

    def test_subscribe_requires_auth(self, api_client, subscription_plan):
        response = api_client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan": str(subscription_plan.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
