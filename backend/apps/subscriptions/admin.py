"""
Subscriptions Django Admin Configuration.
"""

from django.contrib import admin

from .models import (
    Bundle,
    BundleItem,
    BundleSubscription,
    PlanFeature,
    SubscriptionPlan,
    UserSubscription,
)


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 1
    fields = ["feature_key", "feature_label", "feature_value", "is_highlighted", "sort_order"]


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        "name", "tier", "billing_cycle", "price_bdt", "price_credits",
        "max_concurrent_streams", "is_active", "is_highlighted", "sort_order",
    ]
    list_filter = ["tier", "billing_cycle", "is_active", "is_highlighted"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [PlanFeatureInline]
    ordering = ["sort_order", "price_bdt"]


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        "user", "plan", "status", "starts_at", "ends_at",
        "auto_renew", "cancelled_at", "created_at",
    ]
    list_filter = ["status", "auto_renew", "plan__tier"]
    search_fields = ["user__phone_number"]
    raw_id_fields = ["user", "plan"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-created_at"]

    actions = ["expire_selected"]

    def expire_selected(self, request, queryset):
        for sub in queryset:
            sub.expire()
    expire_selected.short_description = "Mark selected subscriptions as expired"


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    extra = 1
    fields = ["plan", "note"]


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ["name", "billing_cycle", "price_bdt", "price_credits", "is_active", "is_featured"]
    list_filter = ["is_active", "is_featured", "billing_cycle"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [BundleItemInline]


@admin.register(BundleSubscription)
class BundleSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "bundle", "status", "starts_at", "ends_at", "auto_renew"]
    list_filter = ["status", "auto_renew"]
    search_fields = ["user__phone_number"]
    raw_id_fields = ["user", "bundle"]
    readonly_fields = ["id", "created_at", "updated_at"]
