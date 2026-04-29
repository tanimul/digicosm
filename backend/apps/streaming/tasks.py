"""
Streaming Platform Celery Tasks.

Tasks
-----
increment_video_views       — Increment view counter for a video
recalculate_video_rating    — Recompute avg_rating and rating_count
expire_stale_sessions       — Expire sessions with no heartbeat (periodic)
cleanup_ended_sessions      — Archive old ended/expired sessions (periodic)
sync_watch_history          — Sync position from ended sessions to watch history
"""

import logging
from datetime import timedelta

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db.models import Avg, Count
from django.utils import timezone

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# View count increment (called after every successful stream start)
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    name="streaming.increment_video_views",
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def increment_video_views(self, video_id: str) -> None:
    """Atomically increment the view_count for a video."""
    try:
        from apps.streaming.models import Video
        from django.db.models import F
        Video.objects.filter(id=video_id).update(
            view_count=F("view_count") + 1
        )
        logger.debug("Incremented view count for video %s", video_id)
    except Exception as exc:
        logger.error("Failed to increment views for video %s: %s", video_id, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Rating recalculation
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    name="streaming.recalculate_video_rating",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def recalculate_video_rating(self, video_id: str) -> None:
    """Recompute avg_rating and rating_count from VideoRating records."""
    try:
        from apps.streaming.models import Video, VideoRating
        agg = VideoRating.objects.filter(
            video_id=video_id, is_visible=True
        ).aggregate(avg=Avg("stars"), count=Count("id"))

        Video.objects.filter(id=video_id).update(
            avg_rating=round(agg["avg"] or 0, 1),
            rating_count=agg["count"] or 0,
        )
        logger.debug("Recalculated rating for video %s: %s", video_id, agg)
    except Exception as exc:
        logger.error("Failed to recalculate rating for video %s: %s", video_id, exc)
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Periodic: expire stale sessions
# ---------------------------------------------------------------------------


@shared_task(
    name="streaming.expire_stale_sessions",
    acks_late=True,
)
def expire_stale_sessions() -> dict:
    """
    Periodic task (run every 5 minutes via Celery beat).
    Mark ACTIVE sessions as EXPIRED if no heartbeat for > 5 minutes.
    """
    from apps.streaming.models import StreamSession, StreamStatus

    cutoff = timezone.now() - timedelta(minutes=5)
    expired_qs = StreamSession.objects.filter(
        status=StreamStatus.ACTIVE,
        last_heartbeat_at__lt=cutoff,
    )
    count = expired_qs.update(
        status=StreamStatus.EXPIRED,
        ended_at=timezone.now(),
    )
    if count:
        logger.info("Expired %d stale stream sessions", count)
    return {"expired": count}


# ---------------------------------------------------------------------------
# Periodic: sync watch history from ended sessions
# ---------------------------------------------------------------------------


@shared_task(
    name="streaming.sync_watch_history_from_sessions",
    acks_late=True,
)
def sync_watch_history_from_sessions() -> dict:
    """
    Periodic task. For all recently ended/expired sessions with a non-zero
    position, ensure watch history is up to date.
    """
    from apps.streaming.models import StreamSession, StreamStatus
    from apps.streaming.services import update_watch_history

    cutoff = timezone.now() - timedelta(hours=1)
    sessions = StreamSession.objects.filter(
        status__in=[StreamStatus.ENDED, StreamStatus.EXPIRED],
        ended_position_seconds__gt=0,
        ended_at__gte=cutoff,
    ).select_related("user", "video")

    synced = 0
    for session in sessions:
        try:
            update_watch_history(session.user, session.video, session.ended_position_seconds)
            synced += 1
        except Exception as exc:
            logger.warning(
                "Failed to sync watch history for session %s: %s", session.id, exc
            )

    logger.info("Synced watch history for %d sessions", synced)
    return {"synced": synced}


# ---------------------------------------------------------------------------
# Periodic: update trending flags based on view velocity
# ---------------------------------------------------------------------------


@shared_task(
    name="streaming.update_trending_videos",
    acks_late=True,
)
def update_trending_videos() -> dict:
    """
    Periodic task (run hourly). Mark top-50 videos by recent views as trending.
    Uses view_count as proxy (a full implementation would track incremental views).
    """
    from apps.streaming.models import ContentStatus, Video

    # Clear existing trending flags
    Video.objects.filter(is_trending=True).update(is_trending=False)

    # Set top 50 by view count as trending
    top_ids = list(
        Video.objects.filter(status=ContentStatus.PUBLISHED)
        .order_by("-view_count")
        .values_list("id", flat=True)[:50]
    )
    updated = Video.objects.filter(id__in=top_ids).update(is_trending=True)
    logger.info("Marked %d videos as trending", updated)
    return {"trending_count": updated}
