"""
Admin Panel URL Configuration.
All routes are prefixed with /api/v1/admin-panel/ in the root urls.py.
"""

from django.urls import path

from .views import (
    AdminPlanListView,
    AdminUserDetailView,
    AdminUserListView,
    AdminVideoListView,
    AdminVideoStatusView,
    AIUsageAnalyticsView,
    FraudAnalyticsView,
    FreezeWalletView,
    ProviderDetailView,
    ProviderKeyDeleteView,
    ProviderKeyListCreateView,
    ProviderListCreateView,
    ProviderToggleView,
    RevenueAnalyticsView,
    StreamingAnalyticsView,
    SubscriptionAnalyticsView,
    UnfreezeWalletView,
)

app_name = "admin_panel"

urlpatterns = [
    # AI Provider management
    path("providers/", ProviderListCreateView.as_view(), name="provider-list"),
    path("providers/<uuid:pk>/", ProviderDetailView.as_view(), name="provider-detail"),
    path("providers/<uuid:pk>/toggle/", ProviderToggleView.as_view(), name="provider-toggle"),
    path("providers/<uuid:pk>/keys/", ProviderKeyListCreateView.as_view(), name="provider-keys"),
    path(
        "providers/<uuid:pk>/keys/<uuid:key_id>/",
        ProviderKeyDeleteView.as_view(),
        name="provider-key-delete",
    ),
    # Analytics
    path("analytics/revenue/", RevenueAnalyticsView.as_view(), name="analytics-revenue"),
    path("analytics/ai-usage/", AIUsageAnalyticsView.as_view(), name="analytics-ai-usage"),
    path("analytics/streaming/", StreamingAnalyticsView.as_view(), name="analytics-streaming"),
    path("analytics/subscriptions/", SubscriptionAnalyticsView.as_view(), name="analytics-subscriptions"),
    path("analytics/fraud/", FraudAnalyticsView.as_view(), name="analytics-fraud"),
    # User management
    path("users/", AdminUserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/", AdminUserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:pk>/freeze-wallet/", FreezeWalletView.as_view(), name="user-freeze-wallet"),
    path("users/<uuid:pk>/unfreeze-wallet/", UnfreezeWalletView.as_view(), name="user-unfreeze-wallet"),
    # Content management
    path("videos/", AdminVideoListView.as_view(), name="video-list"),
    path("videos/<uuid:pk>/status/", AdminVideoStatusView.as_view(), name="video-status"),
    # Subscription plan management
    path("subscriptions/plans/", AdminPlanListView.as_view(), name="subscription-plan-list"),
]
