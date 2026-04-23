"""
Streaming Service Layer — business logic for video access, signed URLs,
and concurrency management.
"""

import logging
from datetime import timedelta
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.streaming.models import (
    AccessLevel,
    StreamSession,
    StreamStatus,
    Video,
    VideoAccessLog,
    WatchHistory,
)

logger = logging.getLogger(__name__)

# Default signed URL TTL: 4 hours
SIGNED_URL_TTL_SECONDS = getattr(settings, "STREAM_SIGNED_URL_TTL", 14400)

# Max active stream sessions per user (overridden by subscription plan)
DEFAULT_MAX_CONCURRENT_STREAMS = 2

# Session heartbeat timeout: if no heartbeat for 5 min, session is expired
HEARTBEAT_TIMEOUT_MINUTES = 5


# ---------------------------------------------------------------------------
# Access Level helpers
# ---------------------------------------------------------------------------

ACCESS_LEVEL_HIERARCHY = {
    AccessLevel.FREE:    0,
    AccessLevel.STARTER: 1,
    AccessLevel.GROWTH:  2,
    AccessLevel.PRO:     3,
    AccessLevel.PPV:     99,  # handled separately
}


def user_plan_level(user) -> int:
    """
    Return the numeric access level for the user's active subscription.
    Falls back to 0 (free) if no active subscription exists.
    """
    try:
        from apps.subscriptions.models import UserSubscription
        sub = UserSubscription.objects.filter(
            user=user,
            status="active",
        ).select_related("plan").first()
        if sub:
            plan_name = sub.plan.access_level  # e.g. "starter", "growth", "pro"
            return ACCESS_LEVEL_HIERARCHY.get(plan_name, 0)
    except Exception:
        pass
    return 0


def user_can_access_video(user, video: Video) -> tuple[bool, str]:
    """
    Return (allowed: bool, reason: str).

    Rules:
    - free content → always accessible
    - ppv → requires credits purchase (checked via PPVAccess)
    - starter/growth/pro → requires matching or higher subscription
    """
    if video.access_level == AccessLevel.FREE:
        return True, "free content"

    if video.access_level == AccessLevel.PPV:
        # Check for a valid PPV purchase
        from apps.streaming.models import VideoAccessLog
        # Simplified: check wallet for ppv purchase record
        # Full implementation would check a PPVPurchase model
        return False, "ppv_required"

    required = ACCESS_LEVEL_HIERARCHY.get(video.access_level, 999)
    user_level = user_plan_level(user)

    if user_level >= required:
        return True, "subscription_valid"

    return False, f"requires_{video.access_level}_plan"


# ---------------------------------------------------------------------------
# Concurrency Control
# ---------------------------------------------------------------------------

def get_active_session_count(user) -> int:
    """Count active (non-expired) stream sessions for a user."""
    cutoff = timezone.now() - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
    return StreamSession.objects.filter(
        user=user,
        status=StreamStatus.ACTIVE,
        last_heartbeat_at__gte=cutoff,
    ).count()


def get_user_max_streams(user) -> int:
    """Return the maximum concurrent streams allowed for the user's plan."""
    try:
        from apps.subscriptions.models import UserSubscription
        sub = UserSubscription.objects.filter(
            user=user, status="active"
        ).select_related("plan").first()
        if sub:
            return sub.plan.max_concurrent_streams
    except Exception:
        pass
    return DEFAULT_MAX_CONCURRENT_STREAMS


def evict_oldest_session(user) -> None:
    """Kick the oldest active session to make room for a new one."""
    cutoff = timezone.now() - timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES)
    oldest = StreamSession.objects.filter(
        user=user,
        status=StreamStatus.ACTIVE,
        last_heartbeat_at__gte=cutoff,
    ).order_by("started_at").first()

    if oldest:
        oldest.status = StreamStatus.KICKED
        oldest.ended_at = timezone.now()
        oldest.save(update_fields=["status", "ended_at"])
        logger.info(
            "Evicted stream session %s for user %s (concurrency limit)",
            oldest.id, user.id,
        )


# ---------------------------------------------------------------------------
# Signed URL Generation
# ---------------------------------------------------------------------------

def generate_signed_url(s3_key: str, ttl_seconds: int = SIGNED_URL_TTL_SECONDS) -> str:
    """
    Generate a pre-signed S3 GET URL for a video file key.

    Falls back to a direct URL (prefixed with MEDIA_URL) in development
    when S3 is not configured (USE_S3 = False).
    """
    if not getattr(settings, "USE_S3", False):
        # Local dev: return media URL directly
        return f"{settings.MEDIA_URL}{s3_key}"

    try:
        s3_client = boto3.client(
            "s3",
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=ttl_seconds,
        )
        return url
    except ClientError as exc:
        logger.error("Failed to generate signed URL for key %s: %s", s3_key, exc)
        raise ValidationError("Failed to generate streaming URL. Please try again.")


# ---------------------------------------------------------------------------
# Main: Request Stream
# ---------------------------------------------------------------------------

@transaction.atomic
def request_stream(
    user,
    video: Video,
    device_id: str,
    quality: str = "720p",
    device_type: str = "web",
    ip_address: str | None = None,
) -> dict:
    """
    Core service: validate access, enforce concurrency, generate signed URL,
    create StreamSession, and return streaming metadata.

    Returns:
        dict with keys: session_id, signed_url, expires_at, quality, subtitles

    Raises:
        ValidationError: if access denied or concurrency limit exceeded
    """
    # 1. Check access rights
    allowed, reason = user_can_access_video(user, video)
    if not allowed:
        VideoAccessLog.objects.create(
            user=user,
            video=video,
            result=VideoAccessLog.AccessResult.DENIED,
            ip_address=ip_address,
            device_id=device_id,
            metadata={"reason": reason},
        )
        raise ValidationError(
            f"Access denied: {reason}",
            code="access_denied",
        )

    # 2. Enforce concurrency limit
    max_streams = get_user_max_streams(user)
    active_count = get_active_session_count(user)

    if active_count >= max_streams:
        evict_oldest_session(user)

    # 3. Resolve video file key (prefer HLS manifest, fallback to direct file)
    quality_obj = video.quality_variants.filter(
        quality=quality, is_ready=True
    ).first()

    if quality_obj:
        file_key = quality_obj.hls_playlist_key or quality_obj.video_file_key
    else:
        # Fallback to master HLS or raw file
        file_key = video.hls_manifest_key or video.video_file_key

    if not file_key:
        raise ValidationError("Video file is not available yet.", code="not_ready")

    # 4. Generate signed URL
    signed_url = generate_signed_url(file_key, ttl_seconds=SIGNED_URL_TTL_SECONDS)
    expires_at = timezone.now() + timedelta(seconds=SIGNED_URL_TTL_SECONDS)

    # 5. Create StreamSession
    session = StreamSession.objects.create(
        user=user,
        video=video,
        device_id=device_id,
        device_type=device_type,
        ip_address=ip_address,
        signed_url_key=file_key,
        signed_url_expires_at=expires_at,
        quality=quality,
        status=StreamStatus.ACTIVE,
    )

    # 6. Audit log
    VideoAccessLog.objects.create(
        user=user,
        video=video,
        session=session,
        result=VideoAccessLog.AccessResult.GRANTED,
        ip_address=ip_address,
        device_id=device_id,
    )

    # 7. Increment video view count (non-blocking, via Celery)
    try:
        from apps.streaming.tasks import increment_video_views
        increment_video_views.delay(str(video.id))
    except Exception:
        pass

    # 8. Build subtitle list
    subtitles = list(
        video.subtitles.values("id", "language", "language_code", "is_default")
    )

    return {
        "session_id": str(session.id),
        "signed_url": signed_url,
        "expires_at": expires_at,
        "quality": quality,
        "subtitles": subtitles,
    }


# ---------------------------------------------------------------------------
# Watch History
# ---------------------------------------------------------------------------

def update_watch_history(user, video: Video, position_seconds: int) -> WatchHistory:
    """Upsert watch history record and sync with completed stream session."""
    history, _ = WatchHistory.objects.get_or_create(
        user=user,
        video=video,
        defaults={"position_seconds": position_seconds},
    )
    if history.position_seconds != position_seconds:
        history.update_progress(position_seconds)
    return history
