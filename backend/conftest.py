"""
Root pytest conftest.py — shared fixtures for all DCE backend tests.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


# ─── User Factories ─────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_user(db):
    """Factory fixture: call make_user() to create a fresh User."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    def _make(
        phone="+8801711111111",
        full_name="Test User",
        is_verified=True,
        is_staff=False,
        **kwargs,
    ):
        return User.objects.create_user(
            phone_number=phone,
            full_name=full_name,
            is_verified=is_verified,
            is_staff=is_staff,
            password="testpass123",
            **kwargs,
        )

    return _make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def admin_user(make_user):
    return make_user(
        phone="+8801722222222",
        full_name="Admin User",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def auth_client(user):
    """APIClient authenticated as `user` via JWT bearer token."""
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    refresh = RefreshToken.for_user(admin_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


# ─── Wallet Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def wallet(user, db):
    """Create a Wallet for the test user if it doesn't already exist."""
    from apps.wallet.models import Wallet as WalletModel
    wallet, _ = WalletModel.objects.get_or_create(
        user=user,
        defaults={"balance_bdt": "500.00", "credits": 5000},
    )
    return wallet


# ─── AI Gateway Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def ai_provider(db):
    from apps.ai_gateway.models import AIProvider, ProviderName
    return AIProvider.objects.create(
        name=ProviderName.OPENAI,
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        is_active=True,
        priority=10,
    )


# ─── Streaming Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def genre(db):
    from apps.streaming.models import Genre
    return Genre.objects.create(name="Action", slug="action")


@pytest.fixture
def video(db, genre):
    from apps.streaming.models import Video, ContentType, ContentStatus, AccessLevel
    v = Video.objects.create(
        title="Test Movie",
        slug="test-movie",
        content_type=ContentType.MOVIE,
        status=ContentStatus.PUBLISHED,
        access_level=AccessLevel.FREE,
    )
    v.genres.add(genre)
    return v


# ─── Subscription Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def subscription_plan(db):
    from apps.subscriptions.models import SubscriptionPlan, PlanTier, BillingCycle
    return SubscriptionPlan.objects.create(
        name="Starter Monthly",
        slug="starter-monthly",
        tier=PlanTier.STARTER,
        billing_cycle=BillingCycle.MONTHLY,
        price_bdt="299.00",
        is_active=True,
    )


# ─── Marketplace Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def vendor(db):
    from apps.marketplace.models import Vendor
    return Vendor.objects.create(
        name="Test Vendor",
        slug="test-vendor",
        is_verified=True,
    )


@pytest.fixture
def product(db, vendor):
    from apps.marketplace.models import Product, ProductType, PricingModel, ProductStatus
    return Product.objects.create(
        name="Test SaaS Tool",
        slug="test-saas-tool",
        vendor=vendor,
        product_type=ProductType.SAAS,
        pricing_model=PricingModel.ONE_TIME,
        price_bdt="999.00",
        status=ProductStatus.PUBLISHED,
    )


# ─── Notification Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def notification_template(db):
    from apps.notifications.models import NotificationTemplate, NotificationChannel
    return NotificationTemplate.objects.create(
        name="Test Template",
        template_key="test.event",
        channel=NotificationChannel.IN_APP,
        subject="Test Subject",
        body="Hello {{ user }}!",
    )
