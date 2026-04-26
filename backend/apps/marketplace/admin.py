"""
Marketplace Django Admin Configuration.
"""

from django.contrib import admin

from .models import (
    Product,
    ProductCategory,
    ProductImage,
    ProductReview,
    ProductSubscription,
    SaaSAccount,
    Vendor,
)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "parent", "sort_order", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_verified", "is_active", "commission_rate_pct", "created_at"]
    list_filter = ["is_verified", "is_active"]
    search_fields = ["name", "slug", "contact_email"]
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ["image", "caption", "sort_order"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name", "product_type", "pricing_model", "price_bdt",
        "price_credits", "status", "is_featured", "purchase_count",
        "avg_rating", "vendor", "published_at",
    ]
    list_filter = ["product_type", "pricing_model", "status", "is_featured"]
    search_fields = ["name", "slug", "tagline"]
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ["vendor", "category"]
    readonly_fields = ["purchase_count", "avg_rating", "rating_count", "created_at", "updated_at"]
    inlines = [ProductImageInline]
    actions = ["publish_selected", "suspend_selected"]

    def publish_selected(self, request, queryset):
        for p in queryset:
            p.publish()
    publish_selected.short_description = "Publish selected products"

    def suspend_selected(self, request, queryset):
        from .models import ProductStatus
        queryset.update(status=ProductStatus.SUSPENDED)
    suspend_selected.short_description = "Suspend selected products"


@admin.register(ProductSubscription)
class ProductSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "status", "starts_at", "ends_at", "auto_renew"]
    list_filter = ["status", "auto_renew"]
    search_fields = ["user__phone_number", "product__name"]
    raw_id_fields = ["user", "product"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(SaaSAccount)
class SaaSAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "account_email", "is_provisioned", "provisioned_at"]
    list_filter = ["is_provisioned"]
    search_fields = ["user__phone_number", "account_email"]
    raw_id_fields = ["user", "product", "subscription"]
    readonly_fields = ["id", "created_at", "updated_at"]
    # Never show encrypted password in admin
    exclude = ["account_password_enc"]


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "stars", "is_visible", "created_at"]
    list_filter = ["stars", "is_visible"]
    search_fields = ["user__phone_number", "body"]
    raw_id_fields = ["user", "product"]
