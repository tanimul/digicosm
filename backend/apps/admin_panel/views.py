"""
Admin Panel API Views — Management endpoints for DCE platform operators.

All endpoints require IsAdminUser permission.

Endpoints
---------
Providers (AI Gateway)
  GET    /admin-panel/providers/                   List AI providers
  POST   /admin-panel/providers/                   Create provider
  GET    /admin-panel/providers/{id}/              Provider detail
  PATCH  /admin-panel/providers/{id}/              Update provider
  POST   /admin-panel/providers/{id}/toggle/       Enable/disable provider
  GET    /admin-panel/providers/{id}/keys/         List API keys for provider
  POST   /admin-panel/providers/{id}/keys/         Add API key
  DELETE /admin-panel/providers/{id}/keys/{key_id}/ Remove API key

Analytics
  GET    /admin-panel/analytics/revenue/           Revenue summary
  GET    /admin-panel/analytics/ai-usage/          AI gateway usage stats
  GET    /admin-panel/analytics/streaming/         Streaming stats
  GET    /admin-panel/analytics/subscriptions/     Subscription stats
  GET    /admin-panel/analytics/fraud/             Fraud detection summary

Users
  GET    /admin-panel/users/                       List users (paginated)
  GET    /admin-panel/users/{id}/                  User detail + wallet + subs
  POST   /admin-panel/users/{id}/freeze-wallet/   Freeze user wallet
  POST   /admin-panel/users/{id}/unfreeze-wallet/ Unfreeze user wallet

Content Management
  GET    /admin-panel/videos/                      All videos (draft + published)
  PATCH  /admin-panel/videos/{id}/status/          Update video status
  GET    /admin-panel/subscriptions/plans/         All plans (for editing)
"""

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
User = get_user_model()


class AdminPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


# ---------------------------------------------------------------------------
# AI Gateway — Provider management
# ---------------------------------------------------------------------------


class ProviderListCreateView(APIView):
    """
    GET  /admin-panel/providers/ — list all AI providers
    POST /admin-panel/providers/ — create a new provider
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.ai_gateway.models import AIProvider
        from apps.ai_gateway.serializers import AIProviderStatusSerializer
        providers = AIProvider.objects.all().order_by("name")
        return Response({
            "success": True,
            "data": AIProviderStatusSerializer(providers, many=True).data,
        })

    def post(self, request):
        from apps.ai_gateway.models import AIProvider
        from apps.ai_gateway.serializers import AIProviderStatusSerializer
        serializer = AIProviderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_201_CREATED,
        )


class ProviderDetailView(APIView):
    """
    GET   /admin-panel/providers/{id}/ — detail
    PATCH /admin-panel/providers/{id}/ — partial update
    """

    permission_classes = [IsAdminUser]

    def _get_provider(self, pk):
        from apps.ai_gateway.models import AIProvider
        return get_object_or_404(AIProvider, id=pk)

    def get(self, request, pk):
        from apps.ai_gateway.serializers import AIProviderStatusSerializer
        p = self._get_provider(pk)
        return Response({"success": True, "data": AIProviderStatusSerializer(p).data})

    def patch(self, request, pk):
        from apps.ai_gateway.serializers import AIProviderStatusSerializer
        p = self._get_provider(pk)
        serializer = AIProviderStatusSerializer(p, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": serializer.data})


class ProviderToggleView(APIView):
    """POST /admin-panel/providers/{id}/toggle/ — enable or disable provider."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        from apps.ai_gateway.models import AIProvider
        p = get_object_or_404(AIProvider, id=pk)
        p.is_active = not p.is_active
        p.save(update_fields=["is_active"])
        return Response({
            "success": True,
            "provider": p.name,
            "is_active": p.is_active,
        })


class ProviderKeyListCreateView(APIView):
    """
    GET  /admin-panel/providers/{id}/keys/ — list keys (masked)
    POST /admin-panel/providers/{id}/keys/ — add new encrypted key
    """

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        from apps.ai_gateway.models import AIProvider, ProviderAPIKey
        provider = get_object_or_404(AIProvider, id=pk)
        keys = ProviderAPIKey.objects.filter(provider=provider).order_by("-created_at")
        data = [
            {
                "id": str(k.id),
                "key_label": k.key_label,
                "is_active": k.is_active,
                "failure_count": k.failure_count,
                "last_used_at": k.last_used_at,
                "created_at": k.created_at,
            }
            for k in keys
        ]
        return Response({"success": True, "data": data})

    def post(self, request, pk):
        from apps.ai_gateway.models import AIProvider, ProviderAPIKey
        provider = get_object_or_404(AIProvider, id=pk)
        raw_key = request.data.get("api_key", "").strip()
        label = request.data.get("key_label", "")
        if not raw_key:
            return Response(
                {"success": False, "error": "api_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        key_obj = ProviderAPIKey.create_with_raw_key(
            provider=provider, raw_key=raw_key, key_label=label
        )
        return Response(
            {"success": True, "id": str(key_obj.id), "key_label": key_obj.key_label},
            status=status.HTTP_201_CREATED,
        )


class ProviderKeyDeleteView(APIView):
    """DELETE /admin-panel/providers/{id}/keys/{key_id}/"""

    permission_classes = [IsAdminUser]

    def delete(self, request, pk, key_id):
        from apps.ai_gateway.models import ProviderAPIKey
        key = get_object_or_404(ProviderAPIKey, id=key_id, provider_id=pk)
        key.delete()
        return Response({"success": True, "message": "Key deleted."})


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class RevenueAnalyticsView(APIView):
    """GET /admin-panel/analytics/revenue/ — revenue summary for last 30/90 days."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.wallet.models import Transaction, TransactionType, TransactionStatus

        days = int(request.query_params.get("days", 30))
        since = timezone.now() - timedelta(days=days)

        deposits = Transaction.objects.filter(
            transaction_type=TransactionType.DEPOSIT,
            status=TransactionStatus.COMPLETED,
            created_at__gte=since,
        ).aggregate(total=Sum("amount"), count=Count("id"))

        subscriptions = Transaction.objects.filter(
            transaction_type=TransactionType.SUBSCRIPTION,
            status=TransactionStatus.COMPLETED,
            created_at__gte=since,
        ).aggregate(total=Sum("amount"), count=Count("id"))

        marketplace = Transaction.objects.filter(
            transaction_type=TransactionType.MARKETPLACE,
            status=TransactionStatus.COMPLETED,
            created_at__gte=since,
        ).aggregate(total=Sum("amount"), count=Count("id"))

        return Response({
            "success": True,
            "period_days": days,
            "deposits_bdt": float(deposits["total"] or 0),
            "deposit_count": deposits["count"] or 0,
            "subscription_credits": float(subscriptions["total"] or 0),
            "subscription_txn_count": subscriptions["count"] or 0,
            "marketplace_credits": float(marketplace["total"] or 0),
            "marketplace_txn_count": marketplace["count"] or 0,
        })


class AIUsageAnalyticsView(APIView):
    """GET /admin-panel/analytics/ai-usage/ — AI gateway usage summary."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.ai_gateway.models import AIUsageLog

        days = int(request.query_params.get("days", 30))
        since = timezone.now() - timedelta(days=days)

        agg = AIUsageLog.objects.filter(created_at__gte=since).aggregate(
            total_requests=Count("id"),
            total_cost=Sum("cost_bdt"),
            total_revenue=Sum("credits_charged"),
        )

        by_provider = list(
            AIUsageLog.objects.filter(created_at__gte=since)
            .values("provider__name")
            .annotate(requests=Count("id"), cost=Sum("cost_bdt"))
            .order_by("-requests")[:10]
        )

        return Response({
            "success": True,
            "period_days": days,
            "total_requests": agg["total_requests"] or 0,
            "total_cost_bdt": float(agg["total_cost"] or 0),
            "total_revenue_credits": float(agg["total_revenue"] or 0),
            "by_provider": by_provider,
        })


class StreamingAnalyticsView(APIView):
    """GET /admin-panel/analytics/streaming/ — streaming platform stats."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.streaming.models import StreamSession, StreamStatus, Video, ContentStatus

        days = int(request.query_params.get("days", 30))
        since = timezone.now() - timedelta(days=days)

        total_sessions = StreamSession.objects.filter(started_at__gte=since).count()
        active_sessions = StreamSession.objects.filter(status=StreamStatus.ACTIVE).count()
        total_videos = Video.objects.filter(status=ContentStatus.PUBLISHED).count()

        top_videos = list(
            Video.objects.filter(status=ContentStatus.PUBLISHED)
            .order_by("-view_count")
            .values("title", "view_count", "content_type")[:10]
        )

        return Response({
            "success": True,
            "period_days": days,
            "sessions_in_period": total_sessions,
            "active_sessions_now": active_sessions,
            "published_videos": total_videos,
            "top_videos": top_videos,
        })


class SubscriptionAnalyticsView(APIView):
    """GET /admin-panel/analytics/subscriptions/ — subscription stats."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.subscriptions.models import UserSubscription, SubscriptionStatus

        by_status = dict(
            UserSubscription.objects.values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )

        by_plan = list(
            UserSubscription.objects.filter(status=SubscriptionStatus.ACTIVE)
            .values("plan__name", "plan__tier")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        return Response({
            "success": True,
            "by_status": by_status,
            "active_by_plan": by_plan,
            "total_active": by_status.get(SubscriptionStatus.ACTIVE, 0),
        })


class FraudAnalyticsView(APIView):
    """GET /admin-panel/analytics/fraud/ — fraud detection summary."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.wallet.models import WalletAuditLog
        from apps.streaming.models import VideoAccessLog

        days = int(request.query_params.get("days", 7))
        since = timezone.now() - timedelta(days=days)

        stream_fraud = VideoAccessLog.objects.filter(
            result="fraud",
            created_at__gte=since,
        ).count()

        fraud_events = list(
            WalletAuditLog.objects.filter(
                created_at__gte=since,
                action="OVERDRAFT_PREVENTED",
            ).values("action", "created_at", "user_id")[:20]
        )

        return Response({
            "success": True,
            "period_days": days,
            "stream_fraud_blocks": stream_fraud,
            "wallet_fraud_events": fraud_events,
        })


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


class AdminUserListView(APIView):
    """GET /admin-panel/users/ — paginated user list."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.accounts.serializers import UserProfileSerializer

        page_size = int(request.query_params.get("page_size", 50))
        page = int(request.query_params.get("page", 1))
        search = request.query_params.get("search", "")

        qs = User.objects.all().order_by("-date_joined")
        if search:
            qs = qs.filter(phone_number__icontains=search)

        total = qs.count()
        offset = (page - 1) * page_size
        users = qs[offset: offset + page_size]

        return Response({
            "success": True,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": UserProfileSerializer(users, many=True).data,
        })


class AdminUserDetailView(APIView):
    """GET /admin-panel/users/{id}/ — user detail with wallet + subscriptions."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        from apps.accounts.serializers import UserProfileSerializer
        from apps.wallet.models import Wallet
        from apps.wallet.serializers import WalletBalanceSerializer
        from apps.subscriptions.models import UserSubscription, SubscriptionStatus
        from apps.subscriptions.serializers import UserSubscriptionSerializer

        user = get_object_or_404(User, id=pk)
        wallet = Wallet.objects.filter(user=user).first()
        active_subs = UserSubscription.objects.filter(
            user=user,
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE],
        ).select_related("plan")

        return Response({
            "success": True,
            "user": UserProfileSerializer(user).data,
            "wallet": WalletBalanceSerializer(wallet).data if wallet else None,
            "active_subscriptions": UserSubscriptionSerializer(active_subs, many=True).data,
        })


class FreezeWalletView(APIView):
    """POST /admin-panel/users/{id}/freeze-wallet/"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        from apps.wallet.models import Wallet
        user = get_object_or_404(User, id=pk)
        wallet = get_object_or_404(Wallet, user=user)
        wallet.is_frozen = True
        wallet.save(update_fields=["is_frozen"])
        logger.warning("Admin %s froze wallet for user %s", request.user.id, pk)
        return Response({"success": True, "message": f"Wallet frozen for user {pk}."})


class UnfreezeWalletView(APIView):
    """POST /admin-panel/users/{id}/unfreeze-wallet/"""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        from apps.wallet.models import Wallet
        user = get_object_or_404(User, id=pk)
        wallet = get_object_or_404(Wallet, user=user)
        wallet.is_frozen = False
        wallet.save(update_fields=["is_frozen"])
        logger.info("Admin %s unfroze wallet for user %s", request.user.id, pk)
        return Response({"success": True, "message": f"Wallet unfrozen for user {pk}."})


# ---------------------------------------------------------------------------
# Content Management
# ---------------------------------------------------------------------------


class AdminVideoListView(APIView):
    """GET /admin-panel/videos/ — all videos including drafts."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.streaming.models import Video
        from apps.streaming.serializers import VideoListSerializer

        status_filter = request.query_params.get("status")
        qs = Video.objects.all().order_by("-created_at")
        if status_filter:
            qs = qs.filter(status=status_filter)

        page_size = int(request.query_params.get("page_size", 50))
        page = int(request.query_params.get("page", 1))
        total = qs.count()
        offset = (page - 1) * page_size

        return Response({
            "success": True,
            "total": total,
            "data": VideoListSerializer(qs[offset: offset + page_size], many=True).data,
        })


class AdminVideoStatusView(APIView):
    """PATCH /admin-panel/videos/{id}/status/ — update video status."""

    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        from apps.streaming.models import Video, ContentStatus
        video = get_object_or_404(Video, id=pk)
        new_status = request.data.get("status")
        if new_status not in ContentStatus.values:
            return Response(
                {"success": False, "error": f"Invalid status. Choose from {ContentStatus.values}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if new_status == ContentStatus.PUBLISHED:
            video.publish()
        else:
            video.status = new_status
            video.save(update_fields=["status", "updated_at"])
        return Response({"success": True, "status": video.status})


# ---------------------------------------------------------------------------
# Subscription Plan Management (admin read-write access)
# ---------------------------------------------------------------------------


class AdminPlanListView(APIView):
    """GET /admin-panel/subscriptions/plans/ — all plans for admin management."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.subscriptions.models import SubscriptionPlan
        from apps.subscriptions.serializers import SubscriptionPlanSerializer
        plans = SubscriptionPlan.objects.all().prefetch_related("features").order_by("sort_order")
        return Response({
            "success": True,
            "data": SubscriptionPlanSerializer(plans, many=True).data,
        })
