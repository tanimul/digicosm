"""
Marketplace App Models — DCE Digital Product Marketplace.

Models
------
ProductCategory     — Hierarchical categories for products
Vendor              — Verified vendor / publisher
Product             — Core marketplace product entity
ProductImage        — Product screenshots / media
ProductSubscription — User's subscription to a SaaS/recurring product
SaaSAccount         — Provisioned SaaS account credentials for a user
ProductReview       — User rating and review for a product
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------


class ProductType(models.TextChoices):
    SAAS            = "saas",            _("SaaS Application")
    AI_TOOL         = "ai_tool",         _("AI Tool")
    DIGITAL_SERVICE = "digital_service", _("Digital Service")
    BUNDLE          = "bundle",          _("Bundle")
    COURSE          = "course",          _("Online Course")
    TEMPLATE        = "template",        _("Template / Asset")
    API_ACCESS      = "api_access",      _("API Access")


class PricingModel(models.TextChoices):
    ONE_TIME    = "one_time",    _("One-Time Purchase")
    MONTHLY     = "monthly",     _("Monthly Subscription")
    YEARLY      = "yearly",      _("Yearly Subscription")
    PAY_PER_USE = "pay_per_use", _("Pay Per Use")
    FREE        = "free",        _("Free")


class ProductStatus(models.TextChoices):
    DRAFT     = "draft",     _("Draft")
    PUBLISHED = "published", _("Published")
    SUSPENDED = "suspended", _("Suspended")
    ARCHIVED  = "archived",  _("Archived")


class SubscriptionStatus(models.TextChoices):
    ACTIVE    = "active",    _("Active")
    GRACE     = "grace",     _("Grace Period")
    EXPIRED   = "expired",   _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


# ---------------------------------------------------------------------------
# ProductCategory
# ---------------------------------------------------------------------------


class ProductCategory(models.Model):
    """Hierarchical category tree for marketplace products."""

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=128, unique=True, db_index=True)
    slug        = models.SlugField(max_length=128, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    icon        = models.CharField(max_length=64, blank=True, default="")
    parent      = models.ForeignKey(
                      "self",
                      on_delete=models.SET_NULL,
                      null=True, blank=True,
                      related_name="subcategories",
                  )
    sort_order  = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Product Category")
        verbose_name_plural = _("Product Categories")
        ordering            = ["sort_order", "name"]

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent.name} › {self.name}"
        return self.name


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


class Vendor(models.Model):
    """
    A verified vendor / publisher on the marketplace.
    Vendors own Products. DCE admins manage vendor verification.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name         = models.CharField(max_length=256, unique=True, db_index=True)
    slug         = models.SlugField(max_length=256, unique=True, db_index=True)
    description  = models.TextField(blank=True, default="")
    logo         = models.ImageField(upload_to="vendors/logos/%Y/%m/", blank=True, null=True)
    website_url  = models.URLField(max_length=512, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    # Revenue sharing
    commission_rate_pct = models.DecimalField(
                              max_digits=5, decimal_places=2, default=Decimal("20.00"),
                              help_text=_("DCE commission percentage on each sale"),
                          )

    is_verified  = models.BooleanField(default=False, db_index=True)
    is_active    = models.BooleanField(default=True, db_index=True)
    metadata     = models.JSONField(default=dict, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Vendor")
        verbose_name_plural = _("Vendors")
        ordering            = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class Product(models.Model):
    """
    Core product entity for the marketplace.

    Supports multiple product types (SaaS, AI tool, course, bundle, etc.)
    with flexible pricing models.
    """

    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor            = models.ForeignKey(
                            Vendor,
                            on_delete=models.PROTECT,
                            related_name="products",
                        )
    category          = models.ForeignKey(
                            ProductCategory,
                            on_delete=models.SET_NULL,
                            null=True, blank=True,
                            related_name="products",
                        )

    # Identity
    name              = models.CharField(max_length=256, db_index=True)
    slug              = models.SlugField(max_length=256, unique=True, db_index=True)
    tagline           = models.CharField(max_length=256, blank=True, default="")
    description       = models.TextField(blank=True, default="")
    features          = models.JSONField(
                            default=list, blank=True,
                            help_text=_("List of feature bullet points"),
                        )

    # Classification
    product_type      = models.CharField(
                            max_length=20,
                            choices=ProductType.choices,
                            default=ProductType.SAAS,
                            db_index=True,
                        )
    pricing_model     = models.CharField(
                            max_length=12,
                            choices=PricingModel.choices,
                            default=PricingModel.MONTHLY,
                            db_index=True,
                        )

    # Pricing
    price_bdt         = models.DecimalField(
                            max_digits=10, decimal_places=2, default=Decimal("0"),
                            help_text=_("Price in BDT"),
                        )
    price_credits     = models.DecimalField(
                            max_digits=12, decimal_places=2, default=Decimal("0"),
                            help_text=_("Price in platform credits"),
                        )

    # Access limits (for SaaS/shared plans)
    max_users         = models.PositiveSmallIntegerField(
                            default=1,
                            help_text=_("Max seats/accounts per subscription"),
                        )

    # Media
    thumbnail         = models.ImageField(
                            upload_to="products/thumbnails/%Y/%m/",
                            blank=True, null=True,
                        )
    banner_image      = models.ImageField(
                            upload_to="products/banners/%Y/%m/",
                            blank=True, null=True,
                        )
    demo_url          = models.URLField(max_length=512, blank=True, default="")
    external_url      = models.URLField(
                            max_length=512, blank=True, default="",
                            help_text=_("External product / signup URL"),
                        )

    # Stats
    purchase_count    = models.PositiveBigIntegerField(default=0)
    avg_rating        = models.DecimalField(max_digits=3, decimal_places=1, default=Decimal("0.0"))
    rating_count      = models.PositiveIntegerField(default=0)

    # Status
    status            = models.CharField(
                            max_length=12,
                            choices=ProductStatus.choices,
                            default=ProductStatus.DRAFT,
                            db_index=True,
                        )
    is_featured       = models.BooleanField(default=False, db_index=True)
    sort_order        = models.PositiveIntegerField(default=0)
    tags              = models.JSONField(default=list, blank=True)

    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)
    published_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = _("Product")
        verbose_name_plural = _("Products")
        ordering            = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["product_type", "status"]),
            models.Index(fields=["is_featured", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.product_type})"

    def publish(self) -> None:
        self.status = ProductStatus.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at", "updated_at"])


# ---------------------------------------------------------------------------
# ProductImage
# ---------------------------------------------------------------------------


class ProductImage(models.Model):
    """Additional screenshots / media assets for a product."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product    = models.ForeignKey(
                     Product,
                     on_delete=models.CASCADE,
                     related_name="images",
                 )
    image      = models.ImageField(upload_to="products/images/%Y/%m/")
    caption    = models.CharField(max_length=256, blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order"]
        verbose_name        = _("Product Image")
        verbose_name_plural = _("Product Images")


# ---------------------------------------------------------------------------
# ProductSubscription
# ---------------------------------------------------------------------------


class ProductSubscription(models.Model):
    """
    A user's subscription to a recurring marketplace product (SaaS, AI tool, etc.).
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
                      User,
                      on_delete=models.CASCADE,
                      related_name="product_subscriptions",
                  )
    product     = models.ForeignKey(
                      Product,
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
        verbose_name        = _("Product Subscription")
        verbose_name_plural = _("Product Subscriptions")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "ends_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.product.name} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE)


# ---------------------------------------------------------------------------
# SaaSAccount
# ---------------------------------------------------------------------------


class SaaSAccount(models.Model):
    """
    Provisioned SaaS account details for a user who has purchased a SaaS product.

    Credentials are stored encrypted. The vendor API provisions the account
    and our webhook/task stores the resulting credentials here.
    """

    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription         = models.OneToOneField(
                               ProductSubscription,
                               on_delete=models.CASCADE,
                               related_name="saas_account",
                           )
    user                 = models.ForeignKey(
                               User,
                               on_delete=models.CASCADE,
                               related_name="saas_accounts",
                           )
    product              = models.ForeignKey(
                               Product,
                               on_delete=models.CASCADE,
                               related_name="saas_accounts",
                           )

    # Provisioned credentials (stored encrypted via Fernet in production)
    account_username     = models.CharField(max_length=256, blank=True, default="")
    account_password_enc = models.TextField(
                               blank=True, default="",
                               help_text=_("Fernet-encrypted account password"),
                           )
    account_email        = models.EmailField(blank=True, default="")
    login_url            = models.URLField(max_length=512, blank=True, default="")

    # Extra provisioning data from vendor
    metadata             = models.JSONField(default=dict, blank=True)

    is_provisioned       = models.BooleanField(default=False, db_index=True)
    provisioned_at       = models.DateTimeField(null=True, blank=True)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("SaaS Account")
        verbose_name_plural = _("SaaS Accounts")

    def __str__(self) -> str:
        return f"{self.user} — {self.product.name} SaaS account"


# ---------------------------------------------------------------------------
# ProductReview
# ---------------------------------------------------------------------------


class ProductReview(models.Model):
    """User rating and text review for a marketplace product."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
                     User,
                     on_delete=models.CASCADE,
                     related_name="product_reviews",
                 )
    product    = models.ForeignKey(
                     Product,
                     on_delete=models.CASCADE,
                     related_name="reviews",
                 )
    stars      = models.PositiveSmallIntegerField(
                     validators=[MinValueValidator(1), MaxValueValidator(5)],
                 )
    title      = models.CharField(max_length=256, blank=True, default="")
    body       = models.TextField(blank=True, default="")
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Product Review")
        verbose_name_plural = _("Product Reviews")
        unique_together     = [("user", "product")]
        ordering            = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} rated {self.product.name}: {self.stars}/5"
