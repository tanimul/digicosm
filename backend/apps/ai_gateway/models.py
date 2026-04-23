"""
AI Gateway Models — Digital Consumption Ecosystem Platform.

Provides the complete data layer for multi-provider AI routing, key management,
usage logging, conversation history, and billing integration.
"""

import hashlib
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Return a Fernet instance using FERNET_KEY from settings."""
    key = getattr(settings, "FERNET_KEY", None)
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not configured in settings. "
            "Generate one with: from cryptography.fernet import Fernet; print(Fernet.generate_key())"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _sha256_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Choice classes
# ---------------------------------------------------------------------------

class ProviderName(models.TextChoices):
    OPENAI    = "openai",    _("OpenAI")
    CLAUDE    = "claude",    _("Anthropic Claude")
    DEEPSEEK  = "deepseek",  _("DeepSeek")
    GEMINI    = "gemini",    _("Google Gemini")
    COHERE    = "cohere",    _("Cohere")
    CUSTOM    = "custom",    _("Custom")


class ServiceType(models.TextChoices):
    CHAT             = "CHAT",             _("Chat / Text Completion")
    IMAGE_GENERATION = "IMAGE_GENERATION", _("Image Generation")
    AUDIO            = "AUDIO",            _("Audio / Speech")
    EMBEDDING        = "EMBEDDING",        _("Embedding")
    VISION           = "VISION",           _("Vision / Image Understanding")
    VIDEO            = "VIDEO",            _("Video Generation")


class UsageStatus(models.TextChoices):
    SUCCESS      = "SUCCESS",      _("Success")
    FAILED       = "FAILED",       _("Failed")
    TIMEOUT      = "TIMEOUT",      _("Timeout")
    RATE_LIMITED = "RATE_LIMITED", _("Rate Limited")


class MessageRole(models.TextChoices):
    USER      = "user",      _("User")
    ASSISTANT = "assistant", _("Assistant")
    SYSTEM    = "system",    _("System")


# ---------------------------------------------------------------------------
# AIProvider
# ---------------------------------------------------------------------------

class AIProvider(models.Model):
    """
    Represents an upstream AI provider (OpenAI, Anthropic, DeepSeek, etc.).

    Health and rate-limit counters are updated by Celery tasks and Redis.
    The ``priority`` field controls which provider is preferred during routing
    (lower value = higher priority).
    """

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name            = models.CharField(
                          max_length=32,
                          choices=ProviderName.choices,
                          unique=True,
                          db_index=True,
                      )
    display_name    = models.CharField(max_length=128)
    base_url        = models.URLField(max_length=512)
    is_active       = models.BooleanField(default=True, db_index=True)
    is_healthy      = models.BooleanField(
                          default=True,
                          help_text=_("Updated automatically by health-check Celery task"),
                      )
    priority        = models.PositiveIntegerField(
                          default=100,
                          help_text=_("Lower value = higher routing priority"),
                      )

    # Rate limits
    max_rpm                = models.PositiveIntegerField(
                                 default=60,
                                 help_text=_("Maximum requests per minute (provider-level)"),
                             )
    max_daily_requests     = models.PositiveIntegerField(
                                 default=10_000,
                                 help_text=_("Maximum requests per day across all keys"),
                             )

    # Counters (mostly maintained in Redis, synced periodically)
    current_rpm_count      = models.PositiveIntegerField(default=0)
    total_requests_served  = models.PositiveBigIntegerField(default=0)
    failure_count          = models.PositiveBigIntegerField(default=0)

    last_health_check      = models.DateTimeField(null=True, blank=True)
    metadata               = models.JSONField(
                                 default=dict,
                                 blank=True,
                                 help_text=_("Provider-specific configuration (e.g. organisation ID, API version)"),
                             )

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("AI Provider")
        verbose_name_plural = _("AI Providers")
        ordering            = ["priority", "name"]

    def __str__(self) -> str:
        status = "✓" if self.is_active and self.is_healthy else "✗"
        return f"[{status}] {self.display_name} (priority={self.priority})"

    def mark_healthy(self) -> None:
        self.is_healthy       = True
        self.last_health_check = timezone.now()
        self.save(update_fields=["is_healthy", "last_health_check", "updated_at"])

    def mark_unhealthy(self) -> None:
        self.is_healthy        = False
        self.failure_count    += 1
        self.last_health_check = timezone.now()
        self.save(update_fields=["is_healthy", "failure_count", "last_health_check", "updated_at"])


# ---------------------------------------------------------------------------
# ProviderAPIKey
# ---------------------------------------------------------------------------

class ProviderAPIKey(models.Model):
    """
    An individual API key belonging to an :class:`AIProvider`.

    Keys are stored Fernet-encrypted.  A SHA-256 hash of the plaintext is
    stored alongside so the key can be identified without decryption.

    Rate-limit counters are primarily Redis-backed; the DB fields are
    periodically synced / reset by Celery tasks.
    """

    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider            = models.ForeignKey(
                              AIProvider,
                              on_delete=models.CASCADE,
                              related_name="api_keys",
                          )
    key_label           = models.CharField(
                              max_length=128,
                              help_text=_("Human-readable label, e.g. 'key-pool-1'"),
                          )
    encrypted_key       = models.BinaryField(
                              help_text=_("Fernet-encrypted API key bytes"),
                          )
    key_hash            = models.CharField(
                              max_length=64,
                              unique=True,
                              db_index=True,
                              help_text=_("SHA-256 of the plaintext key for identification"),
                          )

    is_active           = models.BooleanField(default=True, db_index=True)
    priority            = models.PositiveIntegerField(
                              default=100,
                              help_text=_("Lower = higher selection priority"),
                          )

    # Limits
    rpm_limit           = models.PositiveIntegerField(
                              default=60,
                              help_text=_("Requests per minute this key supports"),
                          )
    daily_limit         = models.PositiveIntegerField(
                              default=1_000,
                              help_text=_("Maximum requests per calendar day"),
                          )

    # Counters
    current_daily_count = models.PositiveIntegerField(default=0)
    current_rpm_count   = models.PositiveIntegerField(
                              default=0,
                              help_text=_("Redis-based; synced periodically"),
                          )
    failure_count       = models.PositiveIntegerField(default=0)
    total_requests      = models.PositiveBigIntegerField(default=0)

    # Timestamps / state
    last_used_at        = models.DateTimeField(null=True, blank=True)
    last_failure_at     = models.DateTimeField(null=True, blank=True)
    last_error          = models.TextField(blank=True, default="")

    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Provider API Key")
        verbose_name_plural = _("Provider API Keys")
        ordering            = ["provider", "priority"]
        indexes = [
            models.Index(fields=["provider", "is_active", "priority"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider.display_name} — {self.key_label}"

    # ------------------------------------------------------------------
    # Key encryption / decryption
    # ------------------------------------------------------------------

    @classmethod
    def create_with_raw_key(
        cls,
        provider: AIProvider,
        raw_key: str,
        key_label: str,
        **kwargs,
    ) -> "ProviderAPIKey":
        """Factory: encrypt ``raw_key`` and persist the model."""
        fernet        = _get_fernet()
        encrypted     = fernet.encrypt(raw_key.encode())
        key_hash      = _sha256_hash(raw_key)
        return cls.objects.create(
            provider=provider,
            key_label=key_label,
            encrypted_key=encrypted,
            key_hash=key_hash,
            **kwargs,
        )

    def get_decrypted_key(self) -> str:
        """Decrypt and return the plaintext API key."""
        fernet = _get_fernet()
        try:
            raw_bytes = bytes(self.encrypted_key)
            return fernet.decrypt(raw_bytes).decode()
        except InvalidToken as exc:
            raise ValueError(
                f"Failed to decrypt API key '{self.key_label}' — "
                "key may be corrupted or FERNET_KEY has changed."
            ) from exc

    # ------------------------------------------------------------------
    # Availability / usage tracking
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if this key can accept more requests right now."""
        if not self.is_active:
            return False
        if self.current_daily_count >= self.daily_limit:
            return False
        # RPM check is Redis-authoritative; fall back to DB counter
        if self.current_rpm_count >= self.rpm_limit:
            return False
        return True

    @transaction.atomic
    def increment_usage(self) -> None:
        """Atomically bump counters and record last-used timestamp."""
        ProviderAPIKey.objects.filter(pk=self.pk).update(
            current_daily_count=models.F("current_daily_count") + 1,
            total_requests=models.F("total_requests") + 1,
            last_used_at=timezone.now(),
        )
        self.refresh_from_db(fields=["current_daily_count", "total_requests", "last_used_at"])

    @transaction.atomic
    def mark_failure(self, error: str) -> None:
        """Record a failure and deactivate the key if threshold is exceeded."""
        ProviderAPIKey.objects.filter(pk=self.pk).update(
            failure_count=models.F("failure_count") + 1,
            last_failure_at=timezone.now(),
            last_error=error[:2048],
        )
        self.refresh_from_db(fields=["failure_count", "last_failure_at", "last_error"])
        # Auto-deactivate after 10 consecutive failures
        if self.failure_count >= 10:
            ProviderAPIKey.objects.filter(pk=self.pk).update(is_active=False)
            self.is_active = False

    @transaction.atomic
    def reset_daily_count(self) -> None:
        """Reset the daily counter. Called by Celery at midnight."""
        ProviderAPIKey.objects.filter(pk=self.pk).update(
            current_daily_count=0,
            failure_count=0,
            is_active=True,
        )
        self.current_daily_count = 0
        self.failure_count       = 0
        self.is_active           = True


# ---------------------------------------------------------------------------
# AIService
# ---------------------------------------------------------------------------

class AIService(models.Model):
    """
    A specific model/service offered by an :class:`AIProvider`.

    Stores pricing on both the cost side (``cost_per_request_bdt``) and the
    sell side (``sell_price_credits``) to enable automatic margin calculation.
    """

    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider             = models.ForeignKey(
                               AIProvider,
                               on_delete=models.CASCADE,
                               related_name="services",
                           )
    service_name         = models.CharField(
                               max_length=128,
                               db_index=True,
                               help_text=_("Slug-style name, e.g. 'gpt-4o'"),
                           )
    display_name         = models.CharField(max_length=256)
    service_type         = models.CharField(
                               max_length=32,
                               choices=ServiceType.choices,
                               default=ServiceType.CHAT,
                               db_index=True,
                           )
    model_id             = models.CharField(
                               max_length=256,
                               help_text=_("Actual model ID sent in API requests"),
                           )

    is_active            = models.BooleanField(default=True, db_index=True)

    # Pricing
    cost_per_request_bdt = models.DecimalField(
                               max_digits=12,
                               decimal_places=6,
                               default=Decimal("0.000000"),
                               help_text=_("Our cost per request in BDT equivalent"),
                           )
    sell_price_credits   = models.DecimalField(
                               max_digits=12,
                               decimal_places=4,
                               default=Decimal("1.0000"),
                               help_text=_("Credits charged to the user per request"),
                           )

    # Model capabilities
    max_tokens           = models.PositiveIntegerField(
                               default=4096,
                               help_text=_("Maximum output tokens"),
                           )
    context_window       = models.PositiveIntegerField(
                               default=128_000,
                               help_text=_("Total context window in tokens"),
                           )
    supports_streaming   = models.BooleanField(default=True)
    supports_vision      = models.BooleanField(default=False)
    capabilities         = models.JSONField(
                               default=list,
                               blank=True,
                               help_text=_("List of capability strings, e.g. ['function_calling', 'json_mode']"),
                           )

    # Routing
    routing_weight       = models.PositiveIntegerField(
                               default=100,
                               help_text=_("Higher weight = more likely to be selected in weighted routing"),
                           )

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("AI Service")
        verbose_name_plural = _("AI Services")
        ordering            = ["provider", "service_name"]
        unique_together     = [("provider", "service_name")]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.provider.display_name})"

    @property
    def margin_percent(self) -> Decimal:
        """
        Percentage margin = (sell_price_bdt - cost) / sell_price_bdt * 100.

        Converts ``sell_price_credits`` to BDT using the platform rate
        (1 BDT = 10 credits by default).
        """
        from apps.wallet.models import BDT_TO_CREDITS_RATE  # avoid circular at module level
        sell_bdt = (self.sell_price_credits / BDT_TO_CREDITS_RATE).quantize(Decimal("0.000001"))
        if sell_bdt == Decimal("0"):
            return Decimal("0")
        margin = ((sell_bdt - self.cost_per_request_bdt) / sell_bdt * 100).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        return margin


# ---------------------------------------------------------------------------
# AIUsageLog
# ---------------------------------------------------------------------------

class AIUsageLog(models.Model):
    """
    Immutable record of every AI request made through the gateway.

    Captures token usage, credits charged, our underlying BDT cost, and the
    resulting profit.  Used for billing reconciliation, anomaly detection, and
    the daily revenue report Celery task.
    """

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user             = models.ForeignKey(
                           User,
                           on_delete=models.SET_NULL,
                           null=True,
                           related_name="ai_usage_logs",
                       )
    service          = models.ForeignKey(
                           AIService,
                           on_delete=models.SET_NULL,
                           null=True,
                           related_name="usage_logs",
                       )
    provider_key     = models.ForeignKey(
                           ProviderAPIKey,
                           on_delete=models.SET_NULL,
                           null=True,
                           related_name="usage_logs",
                       )

    # Tracing
    request_id       = models.UUIDField(
                           default=uuid.uuid4,
                           db_index=True,
                           help_text=_("Unique ID for this individual request (tracing)"),
                       )
    session_id       = models.UUIDField(
                           null=True,
                           blank=True,
                           db_index=True,
                           help_text=_("Groups multiple requests into a conversation session"),
                       )

    # Token counts
    prompt_tokens     = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens      = models.PositiveIntegerField(default=0)

    # Financials
    credits_charged   = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0"))
    bdt_cost          = models.DecimalField(
                            max_digits=12,
                            decimal_places=6,
                            default=Decimal("0"),
                            help_text=_("Our actual cost in BDT"),
                        )
    profit_bdt        = models.DecimalField(
                            max_digits=12,
                            decimal_places=6,
                            default=Decimal("0"),
                        )

    # Performance
    response_time_ms  = models.PositiveIntegerField(
                            default=0,
                            help_text=_("End-to-end latency in milliseconds"),
                        )

    # Status
    status            = models.CharField(
                            max_length=16,
                            choices=UsageStatus.choices,
                            default=UsageStatus.SUCCESS,
                            db_index=True,
                        )
    error_message     = models.TextField(blank=True, default="")
    cached            = models.BooleanField(
                            default=False,
                            help_text=_("True if response was served from cache"),
                        )
    metadata          = models.JSONField(default=dict, blank=True)

    created_at        = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name        = _("AI Usage Log")
        verbose_name_plural = _("AI Usage Logs")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["service", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        service_name = self.service.display_name if self.service else "unknown"
        return f"Usage({self.user_id}) {service_name} — {self.status} @ {self.created_at:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# AIConversation
# ---------------------------------------------------------------------------

class AIConversation(models.Model):
    """
    Groups multiple :class:`AIMessage` records into a logical conversation.

    The ``session_id`` matches the ``session_id`` in :class:`AIUsageLog`.
    Titles are auto-generated from the first user message (truncated at 120 chars).
    """

    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user                = models.ForeignKey(
                              User,
                              on_delete=models.CASCADE,
                              related_name="ai_conversations",
                          )
    session_id          = models.UUIDField(
                              default=uuid.uuid4,
                              unique=True,
                              db_index=True,
                          )
    title               = models.CharField(
                              max_length=240,
                              blank=True,
                              default="",
                              help_text=_("Auto-generated from first message"),
                          )
    service             = models.ForeignKey(
                              AIService,
                              on_delete=models.SET_NULL,
                              null=True,
                              related_name="conversations",
                          )

    # Aggregated stats (updated on each message)
    message_count       = models.PositiveIntegerField(default=0)
    total_tokens_used   = models.PositiveBigIntegerField(default=0)
    total_credits_used  = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0"))

    is_archived         = models.BooleanField(default=False, db_index=True)

    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("AI Conversation")
        verbose_name_plural = _("AI Conversations")
        ordering            = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["user", "is_archived"]),
        ]

    def __str__(self) -> str:
        return f"{self.title or 'Untitled'} ({self.user_id})"

    def auto_set_title(self, first_message: str) -> None:
        """Set title from the first user message if not already set."""
        if not self.title and first_message:
            self.title = first_message[:120].strip()
            self.save(update_fields=["title", "updated_at"])

    @transaction.atomic
    def record_usage(self, tokens: int, credits: Decimal) -> None:
        """Atomically update aggregated conversation stats."""
        AIConversation.objects.filter(pk=self.pk).update(
            message_count=models.F("message_count") + 1,
            total_tokens_used=models.F("total_tokens_used") + tokens,
            total_credits_used=models.F("total_credits_used") + credits,
            updated_at=timezone.now(),
        )


# ---------------------------------------------------------------------------
# AIMessage
# ---------------------------------------------------------------------------

class AIMessage(models.Model):
    """
    A single message within an :class:`AIConversation`.

    Stores the full message content, role, and token count so conversations
    can be reconstructed for context and displayed in the UI.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
                       AIConversation,
                       on_delete=models.CASCADE,
                       related_name="messages",
                   )
    role         = models.CharField(
                       max_length=16,
                       choices=MessageRole.choices,
                       default=MessageRole.USER,
                   )
    content      = models.TextField()
    tokens       = models.PositiveIntegerField(
                       default=0,
                       help_text=_("Approximate token count for this message"),
                   )
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("AI Message")
        verbose_name_plural = _("AI Messages")
        ordering            = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        preview = self.content[:60].replace("\n", " ")
        return f"[{self.role}] {preview}…"
