"""
API Key Manager — Digital Consumption Ecosystem Platform.

Provides a service-layer abstraction over :class:`ProviderAPIKey` for:
  - Encryption / decryption via Fernet
  - Key rotation (zero-downtime)
  - Access auditing
  - Per-key statistics
  - Health probing (lightweight ping)
"""

import hashlib
import logging
import time
import uuid
from typing import Any

import httpx
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import AIProvider, ProviderAPIKey, _get_fernet, _sha256_hash

logger = logging.getLogger(__name__)

# Cache key for audit logs (in-memory ring buffer before DB flush)
_AUDIT_CACHE_KEY = "ai:key_audit:{key_id}"
_AUDIT_TTL       = 86_400  # 24 hours

# How many audit entries to keep in Redis before eviction
_AUDIT_MAX_ENTRIES = 500


# ---------------------------------------------------------------------------
# APIKeyManager
# ---------------------------------------------------------------------------

class APIKeyManager:
    """
    Centralised service for all API key lifecycle operations.

    Instantiate once or use the class methods directly.
    """

    # ------------------------------------------------------------------
    # Encryption / Decryption
    # ------------------------------------------------------------------

    def encrypt_key(self, raw_key: str) -> bytes:
        """
        Encrypt ``raw_key`` using the project's Fernet secret.

        Returns the encrypted bytes suitable for storing in
        ``ProviderAPIKey.encrypted_key``.
        """
        fernet = _get_fernet()
        return fernet.encrypt(raw_key.encode())

    def decrypt_key(self, encrypted_bytes: bytes) -> str:
        """
        Decrypt ``encrypted_bytes`` back to the plaintext API key string.

        Raises ``ValueError`` if decryption fails (wrong key / corrupted data).
        """
        fernet = _get_fernet()
        try:
            return fernet.decrypt(bytes(encrypted_bytes)).decode()
        except Exception as exc:
            raise ValueError(f"Decryption failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    @transaction.atomic
    def rotate_key(self, provider_key_id: str, new_raw_key: str) -> ProviderAPIKey:
        """
        Replace the encrypted key material for an existing :class:`ProviderAPIKey`.

        Steps:
          1. Lock the row.
          2. Encrypt the new raw key.
          3. Compute the new hash.
          4. Persist, reset failure counters, reactivate.
          5. Emit an audit entry.

        Returns the updated ``ProviderAPIKey`` instance.

        Raises:
            ``ProviderAPIKey.DoesNotExist`` — if ID not found.
            ``ValueError``                 — if ``new_raw_key`` is blank.
        """
        if not new_raw_key or not new_raw_key.strip():
            raise ValueError("new_raw_key must not be blank.")

        pk_obj = ProviderAPIKey.objects.select_for_update().get(pk=provider_key_id)

        encrypted_new  = self.encrypt_key(new_raw_key)
        hash_new       = _sha256_hash(new_raw_key)

        pk_obj.encrypted_key    = encrypted_new
        pk_obj.key_hash         = hash_new
        pk_obj.is_active        = True
        pk_obj.failure_count    = 0
        pk_obj.last_error       = ""
        pk_obj.last_failure_at  = None
        pk_obj.save(update_fields=[
            "encrypted_key",
            "key_hash",
            "is_active",
            "failure_count",
            "last_error",
            "last_failure_at",
            "updated_at",
        ])

        self.audit_key_access(
            provider_key_id=str(provider_key_id),
            user_id="system",
            action="KEY_ROTATED",
        )
        logger.info("API key rotated: %s (%s)", pk_obj.key_label, pk_obj.pk)
        return pk_obj

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def audit_key_access(
        self,
        provider_key_id: str,
        user_id: str,
        action: str,
        extra: dict | None = None,
    ) -> None:
        """
        Record a key access event to a Redis ring buffer.

        Audit events are also written to the Python logger for log-aggregation
        pipelines (e.g. Sentry, ELK).

        ``action`` examples: ``KEY_USED``, ``KEY_ROTATED``, ``KEY_DEACTIVATED``,
        ``KEY_HEALTH_CHECKED``, ``DECRYPT_CALLED``.
        """
        entry = {
            "timestamp":       timezone.now().isoformat(),
            "provider_key_id": str(provider_key_id),
            "user_id":         str(user_id),
            "action":          action,
            "extra":           extra or {},
        }
        logger.info("KEY_AUDIT | %s | user=%s | key=%s", action, user_id, provider_key_id)

        # Push to Redis list (best-effort; never raise)
        try:
            cache_key = _AUDIT_CACHE_KEY.format(key_id=provider_key_id)
            import json
            client = cache.client.get_client()
            client.lpush(cache_key, json.dumps(entry))
            client.ltrim(cache_key, 0, _AUDIT_MAX_ENTRIES - 1)
            client.expire(cache_key, _AUDIT_TTL)
        except Exception as exc:
            logger.warning("Audit cache write failed for key %s: %s", provider_key_id, exc)

    def get_audit_log(self, provider_key_id: str, limit: int = 50) -> list[dict]:
        """
        Return the most recent audit entries for a key (from Redis).

        Falls back to empty list if Redis is unavailable.
        """
        import json
        try:
            cache_key = _AUDIT_CACHE_KEY.format(key_id=provider_key_id)
            entries   = cache.client.get_client().lrange(cache_key, 0, limit - 1)
            return [json.loads(e) for e in entries]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_key_stats(self, provider_key_id: str) -> dict[str, Any]:
        """
        Return a comprehensive statistics dict for a given key.

        Keys returned:
          ``key_id``, ``key_label``, ``provider``, ``is_active``,
          ``total_requests``, ``current_daily_count``, ``daily_limit``,
          ``failure_count``, ``last_used_at``, ``last_failure_at``,
          ``last_error``, ``daily_utilisation_pct``, ``created_at``.
        """
        try:
            pk_obj = ProviderAPIKey.objects.select_related("provider").get(pk=provider_key_id)
        except ProviderAPIKey.DoesNotExist:
            raise ValueError(f"ProviderAPIKey '{provider_key_id}' not found.")

        daily_util = (
            round(pk_obj.current_daily_count / pk_obj.daily_limit * 100, 2)
            if pk_obj.daily_limit > 0 else 0.0
        )

        # Pull live RPM from Redis
        from .routing import _get_redis_rpm, _RPM_KEY_TEMPLATE
        live_rpm = _get_redis_rpm(_RPM_KEY_TEMPLATE.format(key_id=pk_obj.id))

        return {
            "key_id":                str(pk_obj.pk),
            "key_label":             pk_obj.key_label,
            "provider":              pk_obj.provider.display_name,
            "is_active":             pk_obj.is_active,
            "total_requests":        pk_obj.total_requests,
            "current_daily_count":   pk_obj.current_daily_count,
            "daily_limit":           pk_obj.daily_limit,
            "daily_utilisation_pct": daily_util,
            "live_rpm":              live_rpm,
            "rpm_limit":             pk_obj.rpm_limit,
            "failure_count":         pk_obj.failure_count,
            "last_used_at":          pk_obj.last_used_at.isoformat() if pk_obj.last_used_at else None,
            "last_failure_at":       pk_obj.last_failure_at.isoformat() if pk_obj.last_failure_at else None,
            "last_error":            pk_obj.last_error,
            "created_at":            pk_obj.created_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def check_key_health(self, provider_key_id: str) -> bool:
        """
        Perform a lightweight API health probe for the given key.

        For OpenAI-compatible endpoints: calls the ``/models`` endpoint.
        For Anthropic (Claude): sends a minimal messages request with
        ``max_tokens=1`` to confirm the key is accepted.

        Returns True if the key is healthy, False otherwise.
        Updates ``is_healthy`` on the parent :class:`AIProvider`.
        """
        try:
            pk_obj = ProviderAPIKey.objects.select_related("provider").get(pk=provider_key_id)
        except ProviderAPIKey.DoesNotExist:
            raise ValueError(f"ProviderAPIKey '{provider_key_id}' not found.")

        raw_key      = pk_obj.get_decrypted_key()
        provider     = pk_obj.provider
        is_healthy   = False

        try:
            start = time.perf_counter()
            if provider.name == "claude":
                is_healthy = self._probe_claude(raw_key, provider.base_url)
            else:
                is_healthy = self._probe_openai_compatible(raw_key, provider.base_url)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Key health check: key=%s provider=%s healthy=%s latency=%dms",
                pk_obj.key_label, provider.name, is_healthy, elapsed_ms,
            )
        except Exception as exc:
            logger.error("Key health check failed: key=%s error=%s", pk_obj.key_label, exc)
            is_healthy = False

        if is_healthy:
            provider.mark_healthy()
        else:
            provider.mark_unhealthy()

        self.audit_key_access(
            provider_key_id=str(provider_key_id),
            user_id="system",
            action="KEY_HEALTH_CHECKED",
            extra={"healthy": is_healthy},
        )
        return is_healthy

    # ------------------------------------------------------------------
    # Internal probe helpers
    # ------------------------------------------------------------------

    def _probe_openai_compatible(self, api_key: str, base_url: str) -> bool:
        """
        Call GET /models on an OpenAI-compatible endpoint.
        Returns True on HTTP 200, False otherwise.
        """
        url = f"{base_url.rstrip('/')}/models"
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            return resp.status_code == 200

    def _probe_claude(self, api_key: str, base_url: str) -> bool:
        """
        Send a minimal Anthropic messages request (max_tokens=1).
        Returns True if we receive a 200 or 400 (key valid but model may differ).
        """
        url     = f"{base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        }
        payload = {
            "model":      "claude-3-haiku-20240307",
            "max_tokens": 1,
            "messages":   [{"role": "user", "content": "ping"}],
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, headers=headers, json=payload)
            # 200 = success, 400 = bad request (key valid, request issue) — key is healthy
            return resp.status_code in (200, 400)
