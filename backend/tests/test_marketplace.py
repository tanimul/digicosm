"""
Tests for apps.marketplace — Vendor, Product, API endpoints.
"""

from decimal import Decimal

import pytest
from rest_framework import status


# ─── Vendor Model ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestVendorModel:
    def test_create_vendor(self, vendor):
        assert vendor.name == "Test Vendor"
        assert vendor.slug == "test-vendor"
        assert vendor.is_verified is True

    def test_vendor_str(self, vendor):
        assert "Test Vendor" in str(vendor)

    def test_vendor_slug_unique(self, db, vendor):
        from apps.marketplace.models import Vendor
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            Vendor.objects.create(name="Test Vendor 2", slug="test-vendor")


# ─── Product Model ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProductModel:
    def test_create_product(self, product):
        from apps.marketplace.models import ProductType, PricingModel, ProductStatus
        assert product.name == "Test SaaS Tool"
        assert product.product_type == ProductType.SAAS
        assert product.pricing_model == PricingModel.ONE_TIME
        assert product.price_bdt == Decimal("999.00")
        assert product.status == ProductStatus.PUBLISHED

    def test_product_str(self, product):
        assert "Test SaaS Tool" in str(product)

    def test_product_slug_unique(self, db, vendor):
        from apps.marketplace.models import Product, ProductType, PricingModel, ProductStatus
        from django.db import IntegrityError
        Product.objects.create(
            name="Tool A", slug="dup-slug", vendor=vendor,
            product_type=ProductType.SAAS, pricing_model=PricingModel.ONE_TIME,
            price_bdt="100.00", status=ProductStatus.PUBLISHED,
        )
        with pytest.raises(IntegrityError):
            Product.objects.create(
                name="Tool B", slug="dup-slug", vendor=vendor,
                product_type=ProductType.SAAS, pricing_model=PricingModel.ONE_TIME,
                price_bdt="200.00", status=ProductStatus.PUBLISHED,
            )

    def test_published_products_visible(self, db, product):
        from apps.marketplace.models import Product, ProductStatus
        published = Product.objects.filter(status=ProductStatus.PUBLISHED)
        assert product in published

    def test_draft_products_not_published(self, db, vendor):
        from apps.marketplace.models import Product, ProductType, PricingModel, ProductStatus
        draft = Product.objects.create(
            name="Draft Tool", slug="draft-tool", vendor=vendor,
            product_type=ProductType.SAAS, pricing_model=PricingModel.ONE_TIME,
            price_bdt="100.00", status=ProductStatus.DRAFT,
        )
        published = Product.objects.filter(status=ProductStatus.PUBLISHED)
        assert draft not in published


# ─── ProductCategory Model ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProductCategoryModel:
    def test_create_category(self, db):
        from apps.marketplace.models import ProductCategory
        cat = ProductCategory.objects.create(name="SaaS Tools", slug="saas-tools")
        assert cat.name == "SaaS Tools"
        assert cat.parent is None

    def test_parent_str(self, db):
        from apps.marketplace.models import ProductCategory
        parent = ProductCategory.objects.create(name="Software", slug="software-parent")
        child = ProductCategory.objects.create(
            name="CRM", slug="crm", parent=parent
        )
        assert "Software" in str(child)


# ─── Marketplace API Endpoints ────────────────────────────────────────────────

@pytest.mark.django_db
class TestMarketplaceAPI:
    def test_list_products_requires_auth(self, api_client):
        response = api_client.get("/api/v1/marketplace/products/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_products_authenticated(self, auth_client, product):
        response = auth_client.get("/api/v1/marketplace/products/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data

    def test_get_product_detail(self, auth_client, product):
        response = auth_client.get(f"/api/v1/marketplace/products/{product.slug}/")
        assert response.status_code == status.HTTP_200_OK

    def test_filter_by_type(self, auth_client, product):
        response = auth_client.get("/api/v1/marketplace/products/?product_type=saas")
        assert response.status_code == status.HTTP_200_OK

    def test_search_products(self, auth_client, product):
        response = auth_client.get("/api/v1/marketplace/products/?search=SaaS")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] >= 1

    def test_purchase_requires_auth(self, api_client, product):
        response = api_client.post(
            "/api/v1/marketplace/orders/",
            {"product": str(product.id), "quantity": 1},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
