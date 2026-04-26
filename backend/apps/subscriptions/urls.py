"""
Subscriptions URL Configuration.

All routes are prefixed with /api/v1/subscriptions/ in the root urls.py.
"""

from django.urls import path

from .views import (
    BundleDetailView,
    BundleListView,
    CancelSubscriptionView,
    MyBundleSubscriptionListView,
    MySubscriptionListView,
    PlanDetailView,
    PlanListView,
    SubscribeBundleView,
    SubscribePlanView,
    ToggleAutoRenewView,
)

app_name = "subscriptions"

urlpatterns = [
    # Plans
    path("plans/", PlanListView.as_view(), name="plan-list"),
    path("plans/<slug:slug>/", PlanDetailView.as_view(), name="plan-detail"),
    path("subscribe/", SubscribePlanView.as_view(), name="subscribe-plan"),
    # My subscriptions
    path("my/", MySubscriptionListView.as_view(), name="my-subscriptions"),
    path("my/<uuid:pk>/cancel/", CancelSubscriptionView.as_view(), name="cancel-subscription"),
    path("my/<uuid:pk>/auto-renew/", ToggleAutoRenewView.as_view(), name="toggle-auto-renew"),
    # Bundles
    path("bundles/", BundleListView.as_view(), name="bundle-list"),
    path("bundles/<slug:slug>/", BundleDetailView.as_view(), name="bundle-detail"),
    path("bundles/subscribe/", SubscribeBundleView.as_view(), name="subscribe-bundle"),
    path("my/bundles/", MyBundleSubscriptionListView.as_view(), name="my-bundle-subscriptions"),
]
