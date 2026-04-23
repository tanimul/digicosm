"""
AI Gateway Views — Digital Consumption Ecosystem Platform.

Endpoints:
  POST   /ai/chat                     — non-streaming chat
  POST   /ai/stream                   — SSE streaming chat
  GET    /ai/services                 — list available services
  GET    /ai/usage                    — authenticated user's usage history
  GET    /ai/conversations            — list conversations
  GET    /ai/conversations/{id}       — conversation + messages
  DELETE /ai/conversations/{id}       — delete / archive conversation
  GET    /ai/status                   — provider health overview
"""

import logging

from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AIConversation,
    AIProvider,
    AIService,
    AIUsageLog,
)
from .proxy import AIProxyService
from .serializers import (
    AIConversationDetailSerializer,
    AIConversationSerializer,
    AIProviderStatusSerializer,
    AIServiceSerializer,
    AIUsageLogSerializer,
    ChatRequestSerializer,
    ChatResponseSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

class UsageLogPagination(PageNumberPagination):
    page_size             = 20
    page_size_query_param = "page_size"
    max_page_size         = 100


class ConversationCursorPagination(CursorPagination):
    page_size             = 20
    ordering              = "-updated_at"
    cursor_query_param    = "cursor"


# ---------------------------------------------------------------------------
# AIChatView  POST /ai/chat
# ---------------------------------------------------------------------------

class AIChatView(APIView):
    """
    Non-streaming AI chat endpoint.

    Request body::

        {
          "service_id": "<uuid>",
          "messages":   [{"role": "user", "content": "Hello"}],
          "session_id": "<uuid> (optional)",
          "max_tokens": 2048,
          "temperature": 0.7,
          "system_prompt": "You are a helpful assistant."
        }

    Returns the complete assistant response once the provider call finishes.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vd         = serializer.validated_data
        proxy      = AIProxyService()

        try:
            result = proxy.process_request(
                user=request.user,
                service_id=str(vd["service_id"]),
                messages=serializer.get_messages(),
                params=serializer.get_params(),
                session_id=str(vd["session_id"]) if vd.get("session_id") else None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            # ValidationError from wallet (insufficient credits) bubbles as 402
            exc_class = type(exc).__name__
            if "insufficient" in str(exc).lower() or "ValidationError" in exc_class:
                return Response(
                    {"detail": "Insufficient credits.", "error": str(exc)},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )
            logger.exception("Unexpected error in AIChatView: %s", exc)
            return Response(
                {"detail": "An internal error occurred. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        out_serializer = ChatResponseSerializer(data=result)
        out_serializer.is_valid()  # always valid — we control the shape
        return Response(out_serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# AIStreamChatView  POST /ai/stream
# ---------------------------------------------------------------------------

class AIStreamChatView(APIView):
    """
    Server-Sent Events streaming endpoint.

    Returns ``text/event-stream`` chunked response.
    Each chunk: ``data: {"token": "..."} \\n\\n``
    Terminator: ``data: [DONE]\\n\\n``
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vd    = serializer.validated_data
        proxy = AIProxyService()

        try:
            generator = proxy.stream_response(
                user=request.user,
                service_id=str(vd["service_id"]),
                messages=serializer.get_messages(),
                params=serializer.get_params(),
                session_id=str(vd["session_id"]) if vd.get("session_id") else None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            if "insufficient" in str(exc).lower():
                return Response(
                    {"detail": "Insufficient credits."},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )
            logger.exception("Unexpected error in AIStreamChatView: %s", exc)
            return Response({"detail": "Internal error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = StreamingHttpResponse(
            generator,
            content_type="text/event-stream",
        )
        response["Cache-Control"]    = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


# ---------------------------------------------------------------------------
# AIServicesListView  GET /ai/services
# ---------------------------------------------------------------------------

class AIServicesListView(generics.ListAPIView):
    """
    Return all active AI services with pricing and capabilities.

    Results are cached for 5 minutes to avoid repeated DB queries.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AIServiceSerializer

    def get_queryset(self):
        qs = (
            AIService.objects
            .select_related("provider")
            .filter(is_active=True, provider__is_active=True)
            .order_by("provider__priority", "routing_weight")
        )
        # Optional filtering
        service_type = self.request.query_params.get("type")
        if service_type:
            qs = qs.filter(service_type=service_type.upper())
        provider = self.request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider__name=provider.lower())
        return qs

    @method_decorator(cache_page(300))  # 5-minute cache
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# AIUsageHistoryView  GET /ai/usage
# ---------------------------------------------------------------------------

class AIUsageHistoryView(generics.ListAPIView):
    """
    Return the authenticated user's AI usage logs, newest first.

    Supports query params:
      - ``service_id`` — filter by service UUID
      - ``status``     — SUCCESS / FAILED / TIMEOUT / RATE_LIMITED
      - ``date_from``, ``date_to`` — ISO-8601 date range
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AIUsageLogSerializer
    pagination_class   = UsageLogPagination

    def get_queryset(self):
        qs = (
            AIUsageLog.objects
            .select_related("service", "service__provider")
            .filter(user=self.request.user)
            .order_by("-created_at")
        )
        params = self.request.query_params
        if params.get("service_id"):
            qs = qs.filter(service_id=params["service_id"])
        if params.get("status"):
            qs = qs.filter(status=params["status"].upper())
        if params.get("date_from"):
            qs = qs.filter(created_at__date__gte=params["date_from"])
        if params.get("date_to"):
            qs = qs.filter(created_at__date__lte=params["date_to"])
        return qs


# ---------------------------------------------------------------------------
# AIConversationListView  GET /ai/conversations
# ---------------------------------------------------------------------------

class AIConversationListView(generics.ListAPIView):
    """
    List the authenticated user's conversations (non-archived by default).

    Query params:
      - ``archived=true`` — include archived conversations
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AIConversationSerializer
    pagination_class   = ConversationCursorPagination

    def get_queryset(self):
        qs = (
            AIConversation.objects
            .select_related("service", "service__provider")
            .filter(user=self.request.user)
        )
        if self.request.query_params.get("archived", "").lower() != "true":
            qs = qs.filter(is_archived=False)
        return qs.order_by("-updated_at")


# ---------------------------------------------------------------------------
# AIConversationDetailView  GET /ai/conversations/{id}
# ---------------------------------------------------------------------------

class AIConversationDetailView(generics.RetrieveAPIView):
    """
    Return full conversation detail including all messages.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AIConversationDetailSerializer

    def get_object(self):
        conv_id = self.kwargs["pk"]
        try:
            return (
                AIConversation.objects
                .prefetch_related("messages")
                .select_related("service", "service__provider")
                .get(pk=conv_id, user=self.request.user)
            )
        except AIConversation.DoesNotExist:
            raise NotFound("Conversation not found.")


# ---------------------------------------------------------------------------
# AIConversationDeleteView  DELETE /ai/conversations/{id}
# ---------------------------------------------------------------------------

class AIConversationDeleteView(APIView):
    """
    Soft-delete (archive) a conversation.

    The conversation data is retained for billing / audit purposes.
    Hard delete is only available to admins via the admin panel.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        try:
            convo = AIConversation.objects.get(pk=pk, user=request.user)
        except AIConversation.DoesNotExist:
            raise NotFound("Conversation not found.")

        convo.is_archived = True
        convo.save(update_fields=["is_archived", "updated_at"])
        return Response(
            {"detail": "Conversation archived successfully."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# AIProviderStatusView  GET /ai/status
# ---------------------------------------------------------------------------

class AIProviderStatusView(APIView):
    """
    Public-facing (authenticated) provider health status.

    Returns list of active providers with is_healthy flag.
    Cached for 60 seconds to prevent DB hammering.
    """
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(cache_page(60))
    def get(self, request):
        providers = AIProvider.objects.filter(is_active=True).order_by("priority")
        serializer = AIProviderStatusSerializer(providers, many=True)
        return Response({
            "providers": serializer.data,
            "healthy_count":   providers.filter(is_healthy=True).count(),
            "total_count":     providers.count(),
        })
