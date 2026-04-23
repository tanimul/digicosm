"""
AI Gateway Serializers — Digital Consumption Ecosystem Platform.

Covers request validation, response shaping, and read-only history views.
"""

import uuid
from decimal import Decimal

from rest_framework import serializers

from .models import (
    AIConversation,
    AIMessage,
    AIProvider,
    AIService,
    AIUsageLog,
    MessageRole,
    ProviderAPIKey,
    ServiceType,
)


# ---------------------------------------------------------------------------
# Chat request / response
# ---------------------------------------------------------------------------

class MessageSerializer(serializers.Serializer):
    """A single message in a conversation (role + content)."""
    role    = serializers.ChoiceField(choices=MessageRole.choices)
    content = serializers.CharField(
        min_length=1,
        max_length=32_768,
        trim_whitespace=False,
    )


class ChatRequestSerializer(serializers.Serializer):
    """
    Validates inbound POST /ai/chat and POST /ai/stream requests.

    ``service_id`` must reference an active :class:`AIService`.
    ``messages``   must be a non-empty list of role/content dicts.
    ``session_id`` is optional — omit to start a new conversation.
    ``stream``     is only meaningful for the stream endpoint but accepted
                   on both for client flexibility.
    """
    service_id  = serializers.UUIDField()
    messages    = serializers.ListField(
                      child=MessageSerializer(),
                      min_length=1,
                      max_length=200,
                  )
    session_id  = serializers.UUIDField(required=False, allow_null=True, default=None)
    stream      = serializers.BooleanField(default=False)
    max_tokens  = serializers.IntegerField(
                      required=False,
                      min_value=1,
                      max_value=128_000,
                      default=2048,
                  )
    temperature = serializers.FloatField(
                      required=False,
                      min_value=0.0,
                      max_value=2.0,
                      default=0.7,
                  )
    # Optional system prompt shortcut
    system_prompt = serializers.CharField(
                        required=False,
                        allow_blank=True,
                        default="",
                        max_length=8192,
                    )

    def validate_messages(self, value: list) -> list:
        # Ensure at least one user message exists
        roles = [m.get("role") for m in value]
        if "user" not in roles:
            raise serializers.ValidationError(
                "At least one message with role='user' is required."
            )
        return value

    def validate_service_id(self, value: uuid.UUID) -> uuid.UUID:
        from .models import AIService
        if not AIService.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError(
                f"AI service '{value}' does not exist or is currently inactive."
            )
        return value

    def get_params(self) -> dict:
        """Return provider params dict from validated data."""
        data = self.validated_data
        return {
            "max_tokens":  data.get("max_tokens", 2048),
            "temperature": data.get("temperature", 0.7),
        }

    def get_messages(self) -> list[dict]:
        """Return final messages list, prepending system_prompt if provided."""
        data     = self.validated_data
        messages = [dict(m) for m in data["messages"]]
        system   = data.get("system_prompt", "").strip()
        if system:
            # Prepend a system message if not already present
            has_system = any(m["role"] == "system" for m in messages)
            if not has_system:
                messages.insert(0, {"role": "system", "content": system})
        return messages


class ChatResponseSerializer(serializers.Serializer):
    """Shape of a successful non-streaming chat response."""
    content         = serializers.CharField()
    usage           = serializers.DictField()
    credits_charged = serializers.CharField()
    request_id      = serializers.CharField()
    session_id      = serializers.CharField()
    cached          = serializers.BooleanField()
    response_time_ms = serializers.IntegerField()
    status          = serializers.CharField()
    error_message   = serializers.CharField(default="")


# ---------------------------------------------------------------------------
# Provider / service read serializers
# ---------------------------------------------------------------------------

class AIProviderStatusSerializer(serializers.ModelSerializer):
    """Lightweight provider health status for the public status endpoint."""

    class Meta:
        model  = AIProvider
        fields = [
            "id",
            "name",
            "display_name",
            "is_active",
            "is_healthy",
            "priority",
            "last_health_check",
        ]
        read_only_fields = fields


class AIServiceSerializer(serializers.ModelSerializer):
    """
    Full service descriptor for GET /ai/services.

    Exposes pricing, capabilities, and provider name.
    """
    provider_name = serializers.CharField(source="provider.display_name", read_only=True)
    margin_percent = serializers.DecimalField(
        source="margin_percent",  # computed property
        max_digits=6,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model  = AIService
        fields = [
            "id",
            "provider_name",
            "service_name",
            "display_name",
            "service_type",
            "model_id",
            "is_active",
            "sell_price_credits",
            "margin_percent",
            "max_tokens",
            "context_window",
            "supports_streaming",
            "supports_vision",
            "capabilities",
            "routing_weight",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Usage history
# ---------------------------------------------------------------------------

class AIUsageLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for a user's usage history."""
    service_name   = serializers.CharField(source="service.display_name", read_only=True, default="")
    provider_name  = serializers.CharField(source="service.provider.display_name", read_only=True, default="")

    class Meta:
        model  = AIUsageLog
        fields = [
            "id",
            "request_id",
            "session_id",
            "service_name",
            "provider_name",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "credits_charged",
            "response_time_ms",
            "status",
            "error_message",
            "cached",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Conversations & messages
# ---------------------------------------------------------------------------

class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AIMessage
        fields = ["id", "role", "content", "tokens", "created_at"]
        read_only_fields = fields


class AIConversationSerializer(serializers.ModelSerializer):
    """Summary serializer (list view)."""
    service_name = serializers.CharField(source="service.display_name", read_only=True, default="")

    class Meta:
        model  = AIConversation
        fields = [
            "id",
            "session_id",
            "title",
            "service_name",
            "message_count",
            "total_tokens_used",
            "total_credits_used",
            "is_archived",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AIConversationDetailSerializer(serializers.ModelSerializer):
    """Detail serializer — includes full message history."""
    service_name = serializers.CharField(source="service.display_name", read_only=True, default="")
    messages     = AIMessageSerializer(many=True, read_only=True)

    class Meta:
        model  = AIConversation
        fields = [
            "id",
            "session_id",
            "title",
            "service_name",
            "message_count",
            "total_tokens_used",
            "total_credits_used",
            "is_archived",
            "messages",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
