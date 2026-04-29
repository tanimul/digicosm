"""
Subscriptions API Views.

Endpoints
---------
GET    /api/v1/subscriptions/plans/                  List active plans
GET    /api/v1/subscriptions/plans/{slug}/           Plan detail with features
POST   /api/v1/subscriptions/subscribe/              Subscribe to a plan
GET    /api/v1/subscriptions/my/                     Current user subscriptions
POST   /api/v1/subscriptions/my/{id}/cancel/         Cancel subscription
PATCH  /api/v1/subscriptions/my/{id}/auto-renew/     Toggle auto-renew
GET    /api/v1/subscriptions/bundles/                List bundles
GET    /api/v1/subscriptions/bundles/{slug}/         Bundle detail
POST   /api/v1/subscriptions/bundles/subscribe/      Subscribe to bundle
GET    /api/v1/subscriptions/my/bundles/             Current user bundle subscriptions
"""

import logging

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Bundle,
    BundleSubscription,
    SubscriptionPlan,
    SubscriptionStatus,
    UserSubscription,
)
from .serializers import (
    BundleSerializer,
    BundleSubscriptionSerializer,
    CancelSubscriptionSerializer,
    SubscribeBundleSerializer,
    SubscribePlanSerializer,
    SubscriptionPlanSerializer,
    ToggleAutoRenewSerializer,
    UserSubscriptionSerializer,
)
from .services import subscribe_to_bundle, subscribe_to_plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


class PlanListView(generics.ListAPIView):
    """GET /subscriptions/plans/ — list all active subscription plans."""

    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            SubscriptionPlan.objects.filter(is_active=True)
            .prefetch_related("features")
            .order_by("sort_order", "price_bdt")
        )


class PlanDetailView(generics.RetrieveAPIView):
    """GET /subscriptions/plans/{slug}/ — plan detail with full features."""

    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"
    queryset = SubscriptionPlan.objects.filter(is_active=True).prefetch_related("features")


class SubscribePlanView(APIView):
    """
    POST /subscriptions/subscribe/
    Subscribe to a plan. Charges credits from wallet.
    Body: { plan_id, auto_renew }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = get_object_or_404(SubscriptionPlan, id=data["plan_id"], is_active=True)
        try:
            sub = subscribe_to_plan(
                user=request.user,
                plan=plan,
                auto_renew=data.get("auto_renew", True),
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"success": True, "data": UserSubscriptionSerializer(sub).data},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# My Subscriptions
# ---------------------------------------------------------------------------


class MySubscriptionListView(generics.ListAPIView):
    """GET /subscriptions/my/ — current user's subscriptions."""

    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            UserSubscription.objects.filter(user=self.request.user)
            .select_related("plan")
            .order_by("-created_at")
        )


class CancelSubscriptionView(APIView):
    """POST /subscriptions/my/{id}/cancel/ — cancel a subscription."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        sub = get_object_or_404(UserSubscription, id=pk, user=request.user)
        if sub.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE):
            return Response(
                {"success": False, "error": "Subscription is not active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub.cancel(reason=serializer.validated_data.get("cancel_reason", ""))
        return Response({"success": True, "message": "Subscription cancelled."})


class ToggleAutoRenewView(APIView):
    """PATCH /subscriptions/my/{id}/auto-renew/ — toggle auto-renew setting."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        sub = get_object_or_404(UserSubscription, id=pk, user=request.user)
        serializer = ToggleAutoRenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub.auto_renew = serializer.validated_data["auto_renew"]
        sub.save(update_fields=["auto_renew", "updated_at"])
        return Response({
            "success": True,
            "auto_renew": sub.auto_renew,
            "message": f"Auto-renew {'enabled' if sub.auto_renew else 'disabled'}.",
        })


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


class BundleListView(generics.ListAPIView):
    """GET /subscriptions/bundles/"""

    serializer_class = BundleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Bundle.objects.filter(is_active=True)
            .prefetch_related("items__plan")
            .order_by("sort_order", "price_bdt")
        )


class BundleDetailView(generics.RetrieveAPIView):
    """GET /subscriptions/bundles/{slug}/"""

    serializer_class = BundleSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"
    queryset = Bundle.objects.filter(is_active=True).prefetch_related("items__plan")


class SubscribeBundleView(APIView):
    """POST /subscriptions/bundles/subscribe/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeBundleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        bundle = get_object_or_404(Bundle, id=data["bundle_id"], is_active=True)
        try:
            sub = subscribe_to_bundle(
                user=request.user,
                bundle=bundle,
                auto_renew=data.get("auto_renew", True),
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"success": True, "data": BundleSubscriptionSerializer(sub).data},
            status=status.HTTP_201_CREATED,
        )


class MyBundleSubscriptionListView(generics.ListAPIView):
    """GET /subscriptions/my/bundles/"""

    serializer_class = BundleSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            BundleSubscription.objects.filter(user=self.request.user)
            .select_related("bundle")
            .prefetch_related("bundle__items__plan")
            .order_by("-created_at")
        )
