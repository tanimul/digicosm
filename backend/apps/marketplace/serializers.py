"""
Marketplace App Serializers.
"""

from rest_framework import serializers

from .models import (
    Product,
    ProductCategory,
    ProductImage,
    ProductReview,
    ProductSubscription,
    SaaSAccount,
    Vendor,
)


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name", "slug", "description", "icon", "parent", "sort_order"]


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "slug", "description", "logo", "website_url", "is_verified"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "caption", "sort_order"]


class ProductListSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    category = ProductCategorySerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "tagline", "product_type", "pricing_model",
            "price_bdt", "price_credits", "thumbnail", "is_featured",
            "avg_rating", "rating_count", "purchase_count",
            "vendor", "category", "published_at",
        ]


class ProductDetailSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    category = ProductCategorySerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "tagline", "description", "features",
            "product_type", "pricing_model", "price_bdt", "price_credits",
            "max_users", "thumbnail", "banner_image", "demo_url", "external_url",
            "is_featured", "avg_rating", "rating_count", "purchase_count",
            "tags", "vendor", "category", "images", "published_at", "created_at",
        ]


class PurchaseProductSerializer(serializers.Serializer):
    """Input for POST /marketplace/products/{slug}/purchase/"""
    auto_renew = serializers.BooleanField(default=True)


class ProductSubscriptionSerializer(serializers.ModelSerializer):
    product = ProductListSerializer(read_only=True)

    class Meta:
        model = ProductSubscription
        fields = [
            "id", "product", "status", "starts_at", "ends_at",
            "auto_renew", "payment_transaction_id", "created_at",
        ]
        read_only_fields = [
            "id", "status", "starts_at", "ends_at",
            "payment_transaction_id", "created_at",
        ]


class SaaSAccountSerializer(serializers.ModelSerializer):
    """Exposes SaaS account info (never exposes raw password)."""
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SaaSAccount
        fields = [
            "id", "product_name", "account_username", "account_email",
            "login_url", "is_provisioned", "provisioned_at", "created_at",
        ]
        read_only_fields = [f.name for f in SaaSAccount._meta.fields]


class ProductReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductReview
        fields = ["id", "product", "stars", "title", "body", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_stars(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("Stars must be 1–5.")
        return value
