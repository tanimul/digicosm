"""
Marketplace URL Configuration.

All routes are prefixed with /api/v1/marketplace/ in the root urls.py.
"""

from django.urls import path

from .views import (
    FeaturedProductsView,
    MySaaSAccountsView,
    MyProductSubscriptionsView,
    ProductCategoryListView,
    ProductDetailView,
    ProductListView,
    ProductReviewView,
    PurchaseProductView,
    VendorListView,
)

app_name = "marketplace"

urlpatterns = [
    path("categories/", ProductCategoryListView.as_view(), name="category-list"),
    path("vendors/", VendorListView.as_view(), name="vendor-list"),
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/featured/", FeaturedProductsView.as_view(), name="product-featured"),
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="product-detail"),
    path("products/<slug:slug>/purchase/", PurchaseProductView.as_view(), name="product-purchase"),
    path("products/<slug:slug>/review/", ProductReviewView.as_view(), name="product-review"),
    path("my/subscriptions/", MyProductSubscriptionsView.as_view(), name="my-subscriptions"),
    path("my/saas-accounts/", MySaaSAccountsView.as_view(), name="my-saas-accounts"),
]
