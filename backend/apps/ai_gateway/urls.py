"""
AI Gateway URL Patterns — Digital Consumption Ecosystem Platform.

Mount under a prefix such as ``/api/v1/`` in the root URLconf:

    path("api/v1/", include("apps.ai_gateway.urls")),

All endpoints require JWT authentication (IsAuthenticated permission).
"""

from django.urls import path

from .views import (
    AIChatView,
    AIConversationDeleteView,
    AIConversationDetailView,
    AIConversationListView,
    AIProviderStatusView,
    AIServicesListView,
    AIStreamChatView,
    AIUsageHistoryView,
)

app_name = "ai_gateway"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Chat endpoints                                                       #
    # ------------------------------------------------------------------ #
    path(
        "ai/chat",
        AIChatView.as_view(),
        name="ai-chat",
    ),
    path(
        "ai/stream",
        AIStreamChatView.as_view(),
        name="ai-stream",
    ),

    # ------------------------------------------------------------------ #
    # Services catalogue                                                   #
    # ------------------------------------------------------------------ #
    path(
        "ai/services",
        AIServicesListView.as_view(),
        name="ai-services",
    ),

    # ------------------------------------------------------------------ #
    # Usage history                                                        #
    # ------------------------------------------------------------------ #
    path(
        "ai/usage",
        AIUsageHistoryView.as_view(),
        name="ai-usage",
    ),

    # ------------------------------------------------------------------ #
    # Conversations                                                        #
    # ------------------------------------------------------------------ #
    path(
        "ai/conversations",
        AIConversationListView.as_view(),
        name="ai-conversations",
    ),
    path(
        "ai/conversations/<uuid:pk>",
        AIConversationDetailView.as_view(),
        name="ai-conversation-detail",
    ),
    path(
        "ai/conversations/<uuid:pk>/delete",
        AIConversationDeleteView.as_view(),
        name="ai-conversation-delete",
    ),

    # ------------------------------------------------------------------ #
    # Provider status                                                      #
    # ------------------------------------------------------------------ #
    path(
        "ai/status",
        AIProviderStatusView.as_view(),
        name="ai-status",
    ),
]
