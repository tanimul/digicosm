"""
AI Routing Engine — Digital Consumption Ecosystem Platform.

Implements multiple routing strategies:
  - Priority routing  : select the key with the lowest priority value
  - Round-robin       : distribute load evenly across available keys
  - Cost-based        : prefer the cheapest healthy provider
  - Performance-based : prefer the provider with lowest average latency
  - Failover          : skip a failed key and return the next best

Redis is used for real-time RPM counters (INCR / EXPIRE pattern).
"""

import logging
import random
import time
from typing import Optional

from django.core.cache import cache
from django.db.models import Avg, QuerySet

from .models import AIProvider, AIService, ProviderAPIKey

logger = logging.getLogger(__name__)

# Redis key templates
_RPM_KEY_TEMPLATE   = "ai:rpm:key:{key_id}"   # per-key RPM counter
_RPM_PROV_TEMPLATE  = "ai:rpm:prov:{prov_id}"  # per-provider RPM counter
_LATENCY_TEMPLATE   = "ai:latency:prov:{prov_id}"  # rolling average latency (ms)

RPM_WINDOW_SECONDS  = 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redis_rpm(redis_key: str, limit: int) -> int:
    """
    Increment a Redis RPM counter and return the current value.
    Sets a 60-second expiry on first use so the window auto-resets.

    Returns the value *after* increment.  If Redis is unavailable the
    function falls back to returning 0 (no rate limiting from Redis side).
    """
    try:
        current = cache.incr(redis_key)
        # Set TTL only on first increment
        if current == 1:
            cache.expire(redis_key, RPM_WINDOW_SECONDS)
        return current
    except Exception:
        logger.warning("Redis unavailable for RPM counter %s, skipping.", redis_key)
        return 0


def _get_redis_rpm(redis_key: str) -> int:
    """Read current RPM counter without incrementing."""
    try:
        val = cache.get(redis_key)
        return int(val) if val is not None else 0
    except Exception:
        return 0


def _store_latency(provider_id, latency_ms: int) -> None:
    """Push a latency sample into a small Redis list (last 20 values)."""
    key = _LATENCY_TEMPLATE.format(prov_id=provider_id)
    try:
        cache.client.get_client().lpush(key, latency_ms)
        cache.client.get_client().ltrim(key, 0, 19)
        cache.client.get_client().expire(key, 3600)
    except Exception:
        pass  # latency tracking is best-effort


def _avg_latency(provider_id) -> Optional[float]:
    """Return mean latency (ms) for a provider, or None if no data."""
    key = _LATENCY_TEMPLATE.format(prov_id=provider_id)
    try:
        vals = cache.client.get_client().lrange(key, 0, -1)
        if not vals:
            return None
        nums = [float(v) for v in vals]
        return sum(nums) / len(nums)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# AIRoutingEngine
# ---------------------------------------------------------------------------

class AIRoutingEngine:
    """
    Central routing brain for the AI Gateway.

    Usage::

        engine = AIRoutingEngine()
        provider, key = engine.select_provider_and_key(
            service_type="CHAT",
            requirements={"service_name": "gpt-4o"},
        )
    """

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def select_provider_and_key(
        self,
        service_type: str,
        requirements: dict,
    ) -> tuple[AIProvider, ProviderAPIKey]:
        """
        Choose the best provider + key combination for a request.

        Steps:
          1. Get active, healthy providers that serve ``service_type``.
          2. Apply routing strategy (priority by default, with cost/perf
             variants available via ``requirements["strategy"]``).
          3. From the selected provider pick the best available key.
          4. Raise ``ValueError`` if nothing is available.
        """
        service_name = requirements.get("service_name")
        strategy     = requirements.get("strategy", "priority")

        providers = self.get_available_providers(service_name=service_name, service_type=service_type)
        if not providers:
            raise ValueError(
                f"No healthy providers available for service_type={service_type}, "
                f"service_name={service_name!r}"
            )

        if strategy == "cost":
            provider = self.cost_based_routing(providers)
        elif strategy == "performance":
            provider = self.performance_based_routing(providers)
        else:
            # Default: lowest priority number wins
            provider = sorted(providers, key=lambda p: p.priority)[0]

        key = self._select_key(provider, requirements)
        logger.debug(
            "Routing: strategy=%s provider=%s key=%s",
            strategy, provider.name, key.key_label,
        )
        return provider, key

    # ------------------------------------------------------------------
    # Provider-level routing
    # ------------------------------------------------------------------

    def cost_based_routing(self, providers: list[AIProvider]) -> AIProvider:
        """
        Return the provider whose services have the lowest ``cost_per_request_bdt``.
        Falls back to priority order if no cost data exists.
        """
        def _min_cost(p: AIProvider) -> float:
            costs = list(
                p.services.filter(is_active=True)
                .values_list("cost_per_request_bdt", flat=True)
            )
            return float(min(costs)) if costs else float("inf")

        ranked = sorted(providers, key=_min_cost)
        return ranked[0]

    def performance_based_routing(self, providers: list[AIProvider]) -> AIProvider:
        """
        Return the provider with the lowest rolling-average latency.
        Providers without latency data are assigned a high default latency
        and thus ranked lower than measured providers.
        """
        HIGH_LATENCY = 99_999.0

        def _latency(p: AIProvider) -> float:
            val = _avg_latency(p.id)
            return val if val is not None else HIGH_LATENCY

        ranked = sorted(providers, key=_latency)
        return ranked[0]

    # ------------------------------------------------------------------
    # Key-level routing
    # ------------------------------------------------------------------

    def round_robin_routing(self, keys: list[ProviderAPIKey]) -> ProviderAPIKey:
        """
        Select a key using simple random shuffle as a stateless round-robin.
        A Redis-backed counter could be added here for strict ordering if needed.
        """
        available = [k for k in keys if k.is_available()]
        if not available:
            raise ValueError("No available keys for round-robin routing.")
        return random.choice(available)

    def priority_routing(self, keys: list[ProviderAPIKey]) -> ProviderAPIKey:
        """Return the available key with the lowest priority number."""
        available = [k for k in keys if k.is_available()]
        if not available:
            raise ValueError("No available keys for priority routing.")
        return sorted(available, key=lambda k: k.priority)[0]

    def failover(
        self,
        failed_key: ProviderAPIKey,
        service: AIService,
    ) -> tuple[AIProvider, ProviderAPIKey]:
        """
        Called when ``failed_key`` produced an error.

        Marks the key as failed, then attempts to find an alternative key
        on the same provider, and if none exists tries another provider.
        """
        error_msg = f"Failover triggered from key={failed_key.key_label}"
        failed_key.mark_failure(error_msg)

        # Try another key on the same provider first
        alt_keys = list(
            ProviderAPIKey.objects.filter(
                provider=failed_key.provider,
                is_active=True,
            ).exclude(pk=failed_key.pk)
        )
        available = [k for k in alt_keys if k.is_available()]
        if available:
            best = sorted(available, key=lambda k: k.priority)[0]
            return failed_key.provider, best

        # Fall back to another provider entirely
        providers = self.get_available_providers(
            service_name=service.service_name,
            service_type=service.service_type,
        )
        providers = [p for p in providers if p.pk != failed_key.provider_id]
        if not providers:
            raise ValueError(
                f"All providers exhausted — no failover available for service={service.service_name}"
            )
        provider = sorted(providers, key=lambda p: p.priority)[0]
        key      = self._select_key(provider, {})
        return provider, key

    # ------------------------------------------------------------------
    # Provider discovery
    # ------------------------------------------------------------------

    def get_available_providers(
        self,
        service_name: Optional[str] = None,
        service_type: Optional[str] = None,
    ) -> list[AIProvider]:
        """
        Return active, healthy providers that carry at least one active service
        matching the given filters.

        Also enforces provider-level RPM limits via Redis.
        """
        qs = AIProvider.objects.filter(is_active=True, is_healthy=True)

        if service_name or service_type:
            svc_filter = {"services__is_active": True}
            if service_name:
                svc_filter["services__service_name"] = service_name
            if service_type:
                svc_filter["services__service_type"] = service_type
            qs = qs.filter(**svc_filter).distinct()

        result = []
        for provider in qs:
            current_rpm = _get_redis_rpm(_RPM_PROV_TEMPLATE.format(prov_id=provider.id))
            if current_rpm < provider.max_rpm:
                result.append(provider)
            else:
                logger.warning(
                    "Provider %s excluded: RPM limit reached (%d/%d).",
                    provider.name, current_rpm, provider.max_rpm,
                )
        return result

    def check_provider_health(self, provider: AIProvider) -> bool:
        """
        Lightweight Redis-based health check.

        Returns True if the provider is currently marked healthy in the DB
        and its RPM counter is below the configured maximum.
        """
        if not provider.is_healthy or not provider.is_active:
            return False
        current_rpm = _get_redis_rpm(_RPM_PROV_TEMPLATE.format(prov_id=provider.id))
        return current_rpm < provider.max_rpm

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_key(self, provider: AIProvider, requirements: dict) -> ProviderAPIKey:
        """
        Select the best available key for ``provider`` applying RPM checks.
        Raises ``ValueError`` if the provider has no available keys.
        """
        keys = list(
            ProviderAPIKey.objects.filter(provider=provider, is_active=True)
            .order_by("priority")
        )

        # Augment with Redis RPM data
        for key in keys:
            redis_key = _RPM_KEY_TEMPLATE.format(key_id=key.id)
            key._redis_rpm = _get_redis_rpm(redis_key)

        available = [
            k for k in keys
            if k.is_available() and k._redis_rpm < k.rpm_limit
        ]

        if not available:
            raise ValueError(
                f"Provider '{provider.display_name}' has no available API keys "
                f"(all keys exhausted or rate-limited)."
            )

        # Use priority routing by default
        return available[0]

    def record_request_start(self, provider: AIProvider, key: ProviderAPIKey) -> float:
        """
        Increment Redis RPM counters for both provider and key.
        Returns the start timestamp for latency measurement.
        """
        _redis_rpm(_RPM_PROV_TEMPLATE.format(prov_id=provider.id), provider.max_rpm)
        _redis_rpm(_RPM_KEY_TEMPLATE.format(key_id=key.id), key.rpm_limit)
        return time.perf_counter()

    def record_request_end(
        self,
        provider: AIProvider,
        start_time: float,
        success: bool = True,
    ) -> int:
        """
        Record latency for the provider and return elapsed milliseconds.
        """
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        if success:
            _store_latency(provider.id, elapsed_ms)
        return elapsed_ms
