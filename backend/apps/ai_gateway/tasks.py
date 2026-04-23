"""
AI Gateway Celery Tasks — Digital Consumption Ecosystem Platform.

Scheduled tasks:
  - health_check_all_providers    — every 5 minutes
  - reset_daily_api_key_counts    — daily at 00:00 Asia/Dhaka
  - detect_usage_anomalies        — every 15 minutes
  - cleanup_old_conversations     — daily at 02:00
  - calculate_ai_revenue_report   — daily at 01:00
  - refresh_provider_rpm_counters — every minute (safety valve)

Register with Celery Beat via Django admin (django-celery-beat) or hard-code
in CELERY_BEAT_SCHEDULE.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Health-check all providers
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.health_check_all_providers",
    max_retries=2,
    default_retry_delay=30,
    queue="celery",
)
def health_check_all_providers(self):
    """
    Ping every active provider using at least one of its API keys.

    Updates ``AIProvider.is_healthy``, ``last_health_check``, and
    ``failure_count`` via :class:`APIKeyManager.check_key_health`.

    Runs approximately every 5 minutes.
    """
    from .key_manager import APIKeyManager
    from .models import AIProvider, ProviderAPIKey

    manager    = APIKeyManager()
    providers  = AIProvider.objects.filter(is_active=True)
    results    = {"healthy": 0, "unhealthy": 0, "skipped": 0}

    for provider in providers:
        # Use the highest-priority active key for the health probe
        key = (
            ProviderAPIKey.objects
            .filter(provider=provider, is_active=True)
            .order_by("priority")
            .first()
        )
        if not key:
            logger.warning("Provider %s has no active keys — skipping health check.", provider.name)
            results["skipped"] += 1
            continue

        try:
            healthy = manager.check_key_health(str(key.pk))
            if healthy:
                results["healthy"] += 1
            else:
                results["unhealthy"] += 1
        except Exception as exc:
            logger.error("Health check failed for provider %s: %s", provider.name, exc)
            provider.mark_unhealthy()
            results["unhealthy"] += 1

    logger.info(
        "health_check_all_providers completed: healthy=%d unhealthy=%d skipped=%d",
        results["healthy"], results["unhealthy"], results["skipped"],
    )
    return results


# ---------------------------------------------------------------------------
# 2. Reset daily API key counts
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.reset_daily_api_key_counts",
    queue="celery",
)
def reset_daily_api_key_counts(self):
    """
    Reset ``current_daily_count`` and re-enable auto-deactivated keys.

    Scheduled: daily at midnight (00:00 Asia/Dhaka).
    """
    from .models import ProviderAPIKey

    updated = 0
    # Bulk reset via UPDATE query — faster than iterating
    with transaction.atomic():
        updated = ProviderAPIKey.objects.update(
            current_daily_count=0,
            failure_count=0,
            is_active=True,
        )

    # Reset Redis RPM counters too (they expire naturally in 60 s, but
    # this ensures a clean slate at midnight).
    try:
        from .models import AIProvider
        from .routing import _RPM_PROV_TEMPLATE, _RPM_KEY_TEMPLATE
        for provider in AIProvider.objects.all():
            cache.delete(_RPM_PROV_TEMPLATE.format(prov_id=provider.id))
        for key in ProviderAPIKey.objects.all():
            cache.delete(_RPM_KEY_TEMPLATE.format(key_id=key.id))
    except Exception as exc:
        logger.warning("Could not clear Redis RPM counters: %s", exc)

    logger.info("reset_daily_api_key_counts: reset %d keys.", updated)
    return {"keys_reset": updated}


# ---------------------------------------------------------------------------
# 3. Detect usage anomalies
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.detect_usage_anomalies",
    queue="celery",
)
def detect_usage_anomalies(self):
    """
    Flag users or keys with abnormal usage patterns in the last 15 minutes.

    Heuristics applied:
      - User consumes > 500 credits in 15 minutes  → flag
      - A single key gets > 80 % of its daily limit in 15 minutes → flag
      - Error rate > 50 % across any provider in the last 15 minutes → flag

    Anomalies are currently logged; extend this task to trigger alerts
    (Slack webhook, Sentry event, admin notification, etc.).
    """
    from .models import AIUsageLog, ProviderAPIKey, UsageStatus

    window_start = timezone.now() - timedelta(minutes=15)
    anomalies    = []

    # --- User credit spike ---
    user_usage = (
        AIUsageLog.objects
        .filter(created_at__gte=window_start, status=UsageStatus.SUCCESS)
        .values("user_id")
        .annotate(total_credits=Sum("credits_charged"))
        .filter(total_credits__gt=Decimal("500"))
    )
    for row in user_usage:
        msg = f"User {row['user_id']} consumed {row['total_credits']} credits in 15 min."
        logger.warning("ANOMALY | %s", msg)
        anomalies.append({"type": "user_credit_spike", "detail": msg})

    # --- Key daily-limit burndown spike ---
    keys = ProviderAPIKey.objects.filter(is_active=True, daily_limit__gt=0)
    for key in keys:
        recent_count = AIUsageLog.objects.filter(
            created_at__gte=window_start,
            provider_key=key,
        ).count()
        proportion = recent_count / key.daily_limit if key.daily_limit else 0
        if proportion > 0.8:
            msg = (
                f"Key '{key.key_label}' ({key.provider.display_name}) "
                f"hit {recent_count}/{key.daily_limit} ({proportion:.0%}) requests in 15 min."
            )
            logger.warning("ANOMALY | %s", msg)
            anomalies.append({"type": "key_burndown_spike", "detail": msg})

    # --- Provider error rate ---
    from .models import AIProvider
    for provider in AIProvider.objects.filter(is_active=True):
        total = AIUsageLog.objects.filter(
            created_at__gte=window_start,
            service__provider=provider,
        ).count()
        if total < 10:
            continue  # not enough data
        errors = AIUsageLog.objects.filter(
            created_at__gte=window_start,
            service__provider=provider,
            status__in=[UsageStatus.FAILED, UsageStatus.TIMEOUT],
        ).count()
        error_rate = errors / total
        if error_rate > 0.5:
            msg = (
                f"Provider '{provider.display_name}' error rate = "
                f"{error_rate:.0%} ({errors}/{total}) in 15 min."
            )
            logger.warning("ANOMALY | %s", msg)
            anomalies.append({"type": "provider_error_spike", "detail": msg})
            provider.mark_unhealthy()

    logger.info("detect_usage_anomalies: %d anomalies found.", len(anomalies))
    return {"anomalies": anomalies}


# ---------------------------------------------------------------------------
# 4. Cleanup old conversations
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.cleanup_old_conversations",
    queue="celery",
)
def cleanup_old_conversations(self):
    """
    Archive conversations that have had no activity for > 30 days.

    Does NOT delete them — the data is retained for billing/audit.
    Scheduled: daily at 02:00.
    """
    from .models import AIConversation

    cutoff  = timezone.now() - timedelta(days=30)
    updated = (
        AIConversation.objects
        .filter(is_archived=False, updated_at__lt=cutoff)
        .update(is_archived=True)
    )
    logger.info("cleanup_old_conversations: archived %d conversations.", updated)
    return {"archived": updated}


# ---------------------------------------------------------------------------
# 5. Calculate AI revenue report
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.calculate_ai_revenue_report",
    queue="celery",
)
def calculate_ai_revenue_report(self):
    """
    Generate a daily profit/loss report for the AI Gateway.

    Aggregates yesterday's ``AIUsageLog`` records and writes a summary to
    cache (Redis key ``ai:revenue_report:YYYY-MM-DD``) for the admin dashboard.

    Also logs the report via the standard Python logger for log-aggregation.
    Scheduled: daily at 01:00.
    """
    from .models import AIUsageLog, AIProvider, AIService, UsageStatus
    import json

    yesterday     = (timezone.now() - timedelta(days=1)).date()
    report_key    = f"ai:revenue_report:{yesterday.isoformat()}"

    qs = AIUsageLog.objects.filter(
        created_at__date=yesterday,
        status=UsageStatus.SUCCESS,
    )

    totals = qs.aggregate(
        total_requests   = Count("id"),
        total_tokens     = Sum("total_tokens"),
        total_credits    = Sum("credits_charged"),
        total_bdt_cost   = Sum("bdt_cost"),
        total_profit_bdt = Sum("profit_bdt"),
        avg_response_ms  = Avg("response_time_ms"),
    )

    # Per-service breakdown
    by_service = list(
        qs.values("service__service_name", "service__provider__name")
        .annotate(
            requests    = Count("id"),
            tokens      = Sum("total_tokens"),
            credits     = Sum("credits_charged"),
            cost_bdt    = Sum("bdt_cost"),
            profit_bdt  = Sum("profit_bdt"),
        )
        .order_by("-profit_bdt")[:20]
    )

    # Cache-hit rate
    cache_hits  = qs.filter(cached=True).count()
    total_count = totals.get("total_requests") or 0
    cache_rate  = round(cache_hits / total_count * 100, 2) if total_count else 0

    report = {
        "date":              yesterday.isoformat(),
        "total_requests":    total_count,
        "total_tokens":      totals.get("total_tokens") or 0,
        "total_credits":     str(totals.get("total_credits") or "0"),
        "total_bdt_cost":    str(totals.get("total_bdt_cost") or "0"),
        "total_profit_bdt":  str(totals.get("total_profit_bdt") or "0"),
        "avg_response_ms":   round(float(totals.get("avg_response_ms") or 0), 2),
        "cache_hit_rate_pct": cache_rate,
        "by_service":        [
            {
                "service":    r["service__service_name"],
                "provider":   r["service__provider__name"],
                "requests":   r["requests"],
                "tokens":     r["tokens"],
                "credits":    str(r["credits"]),
                "cost_bdt":   str(r["cost_bdt"]),
                "profit_bdt": str(r["profit_bdt"]),
            }
            for r in by_service
        ],
    }

    try:
        cache.set(report_key, json.dumps(report), timeout=86_400 * 7)  # keep 7 days
    except Exception as exc:
        logger.warning("Could not cache revenue report: %s", exc)

    logger.info(
        "AI Revenue Report [%s] — requests=%d profit_bdt=%s cache_rate=%.1f%%",
        yesterday,
        total_count,
        report["total_profit_bdt"],
        cache_rate,
    )
    return report


# ---------------------------------------------------------------------------
# 6. Refresh provider RPM counters (safety valve)
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="ai_gateway.refresh_provider_rpm_counters",
    queue="celery",
)
def refresh_provider_rpm_counters(self):
    """
    Sync Redis RPM counters back to the DB every minute for monitoring.

    Redis keys expire automatically after 60 s, so this task primarily
    writes the current live count to ``AIProvider.current_rpm_count`` and
    ``ProviderAPIKey.current_rpm_count`` for visibility in the admin panel.

    Scheduled: every 60 seconds.
    """
    from .models import AIProvider, ProviderAPIKey
    from .routing import _RPM_KEY_TEMPLATE, _RPM_PROV_TEMPLATE, _get_redis_rpm

    prov_updates = 0
    for provider in AIProvider.objects.filter(is_active=True):
        rpm = _get_redis_rpm(_RPM_PROV_TEMPLATE.format(prov_id=provider.id))
        AIProvider.objects.filter(pk=provider.pk).update(current_rpm_count=rpm)
        prov_updates += 1

    key_updates = 0
    for key in ProviderAPIKey.objects.filter(is_active=True):
        rpm = _get_redis_rpm(_RPM_KEY_TEMPLATE.format(key_id=key.id))
        ProviderAPIKey.objects.filter(pk=key.pk).update(current_rpm_count=rpm)
        key_updates += 1

    logger.debug(
        "refresh_provider_rpm_counters: updated %d providers, %d keys.",
        prov_updates, key_updates,
    )
    return {"providers_updated": prov_updates, "keys_updated": key_updates}
