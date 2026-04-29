"""
Marketplace API Views.

Endpoints
---------
GET    /api/v1/marketplace/categories/                  ProductCategoryListView
GET    /api/v1/marketplace/vendors/                     VendorListView
GET    /api/v1/marketplace/products/                    ProductListView
GET    /api/v1/marketplace/products/featured/           FeaturedProductsView
GET    /api/v1/marketplace/products/{slug}/             ProductDetailView
POST   /api/v1/marketplace/products/{slug}/purchase/    PurchaseProductView
POST   /api/v1/marketplace/products/{slug}/review/      ProductReviewView
GET    /api/v1/marketplace/my/subscriptions/            MyProductSubscriptionsView
GET    /api/v1/marketplace/my/saas-accounts/            MySaaSAccountsView
"""

import logging

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Product,
    ProductCategory,
    ProductReview,
    ProductStatus,
    ProductSubscription,
    SaaSAccount,
    Vendor,
)
from .serializers import (
    ProductCategorySerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductReviewSerializer,
    ProductSubscriptionSerializer,
    PurchaseProductSerializer,
    SaaSAccountSerializer,
    VendorSerializer,
)
from .services import purchase_product

logger = logging.getLogger(__name__)


class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class ProductCategoryListView(generics.ListAPIView):
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAuthenticated]
    queryset = ProductCategory.objects.filter(is_active=True).order_by("sort_order", "name")


class VendorListView(generics.ListAPIView):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]
    queryset = Vendor.objects.filter(is_active=True, is_verified=True).order_by("name")


class ProductListView(generics.ListAPIView):
    """
    GET /marketplace/products/
    Query params: product_type, pricing_model, category, vendor, search
    """

    serializer_class = ProductListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ProductPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "tagline", "description", "tags"]
    ordering_fields = ["published_at", "purchase_count", "avg_rating", "price_credits"]
    ordering = ["-published_at"]

    def get_queryset(self):
        qs = (
            Product.objects.filter(status=ProductStatus.PUBLISHED)
            .select_related("vendor", "category")
        )
        product_type = self.request.query_params.get("product_type")
        if product_type:
            qs = qs.filter(product_type=product_type)

        pricing_model = self.request.query_params.get("pricing_model")
        if pricing_model:
            qs = qs.filter(pricing_model=pricing_model)

        category_slug = self.request.query_params.get("category")
        if category_slug:
            qs = qs.filter(category__slug=category_slug)

        vendor_slug = self.request.query_params.get("vendor")
        if vendor_slug:
            qs = qs.filter(vendor__slug=vendor_slug)

        return qs


class FeaturedProductsView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ProductPagination

    def get_queryset(self):
        return (
            Product.objects.filter(status=ProductStatus.PUBLISHED, is_featured=True)
            .select_related("vendor", "category")
            .order_by("sort_order", "-published_at")
        )


class ProductDetailView(generics.RetrieveAPIView):
    serializer_class = ProductDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"
    queryset = (
        Product.objects.filter(status=ProductStatus.PUBLISHED)
        .select_related("vendor", "category")
        .prefetch_related("images")
    )


# ---------------------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------------------


class PurchaseProductView(APIView):
    """
    POST /marketplace/products/{slug}/purchase/
    Purchase / subscribe to a marketplace product.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, status=ProductStatus.PUBLISHED)
        serializer = PurchaseProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sub = purchase_product(
                user=request.user,
                product=product,
                auto_renew=serializer.validated_data.get("auto_renew", True),
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"success": True, "data": ProductSubscriptionSerializer(sub).data},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class ProductReviewView(APIView):
    """
    POST /marketplace/products/{slug}/review/
    Create or update a product review.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        product = get_object_or_404(Product, slug=slug, status=ProductStatus.PUBLISHED)
        existing = ProductReview.objects.filter(user=request.user, product=product).first()

        serializer = ProductReviewSerializer(
            instance=existing,
            data={**request.data, "product": str(product.id)},
            partial=bool(existing),
        )
        serializer.is_valid(raise_exception=True)

        if existing:
            serializer.save()
        else:
            serializer.save(user=request.user, product=product)

        try:
            from apps.marketplace.tasks import recalculate_product_rating
            recalculate_product_rating.delay(str(product.id))
        except Exception:
            pass

        code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return Response({"success": True, "data": serializer.data}, status=code)


# ---------------------------------------------------------------------------
# My Purchases
# ---------------------------------------------------------------------------


class MyProductSubscriptionsView(generics.ListAPIView):
    """GET /marketplace/my/subscriptions/ — products the user has purchased."""

    serializer_class = ProductSubscriptionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ProductPagination

    def get_queryset(self):
        return (
            ProductSubscription.objects.filter(user=self.request.user)
            .select_related("product__vendor", "product__category")
            .order_by("-created_at")
        )


class MySaaSAccountsView(generics.ListAPIView):
    """GET /marketplace/my/saas-accounts/ — provisioned SaaS accounts."""

    serializer_class = SaaSAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            SaaSAccount.objects.filter(user=self.request.user)
            .select_related("product")
            .order_by("-created_at")
        )
