"""
Streaming Platform Models — Netflix-style video streaming for DCE Bangladesh.

Models
------
Genre            — Content genre tags (Action, Drama, etc.)
Category         — Content category (Movies, Series, Courses, etc.)
Video            — Core video content entity
VideoQuality     — Per-video quality variants (360p, 720p, 1080p, 4K)
VideoSubtitle    — Subtitle/caption tracks per video
Episode          — Series episode linked to a Video
Season           — Season grouping for a series
WatchHistory     — Per-user watch progress tracking
StreamSession    — Active streaming session (concurrency control)
VideoRating      — User star ratings and reviews
VideoAccessLog   — Audit trail for stream access (fraud + compliance)
"""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class ContentType(models.TextChoices):
    MOVIE   = "movie",   _("Movie")
    SERIES  = "series",  _("Series")
    COURSE  = "course",  _("Course")
    TUTORIAL = "tutorial", _("Tutorial")
    DOCUMENTARY = "documentary", _("Documentary")
    SHORT   = "short",   _("Short Film")


class ContentStatus(models.TextChoices):
    DRAFT      = "draft",      _("Draft")
    PROCESSING = "processing", _("Processing")
    PUBLISHED  = "published",  _("Published")
    ARCHIVED   = "archived",   _("Archived")


class VideoQualityLabel(models.TextChoices):
    Q_360P  = "360p",  _("360p SD")
    Q_480P  = "480p",  _("480p SD")
    Q_720P  = "720p",  _("720p HD")
    Q_1080P = "1080p", _("1080p Full HD")
    Q_4K    = "4k",    _("4K Ultra HD")


class AccessLevel(models.TextChoices):
    FREE     = "free",     _("Free")
    STARTER  = "starter",  _("Starter Plan")
    GROWTH   = "growth",   _("Growth Plan")
    PRO      = "pro",      _("Pro Plan")
    PPV      = "ppv",      _("Pay-Per-View")


class StreamStatus(models.TextChoices):
    ACTIVE    = "active",    _("Active")
    ENDED     = "ended",     _("Ended")
    EXPIRED   = "expired",   _("Expired")
    KICKED    = "kicked",    _("Kicked — concurrency limit")


# ---------------------------------------------------------------------------
# Genre
# ---------------------------------------------------------------------------

class Genre(models.Model):
    """Content genre tag (Action, Drama, Technology, etc.)."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=64, unique=True, db_index=True)
    slug       = models.SlugField(max_length=64, unique=True, db_index=True)
    icon       = models.CharField(
                     max_length=64, blank=True, default="",
                     help_text=_("Icon name or emoji for UI display"),
                 )
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Genre")
        verbose_name_plural = _("Genres")
        ordering            = ["name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class Category(models.Model):
    """
    Top-level content category (Movies, Web Series, Online Courses, etc.).
    Supports nested subcategories via parent FK.
    """

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=128, unique=True, db_index=True)
    slug        = models.SlugField(max_length=128, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    thumbnail   = models.ImageField(
                      upload_to="categories/%Y/%m/",
                      blank=True, null=True,
                  )
    parent      = models.ForeignKey(
                      "self",
                      on_delete=models.SET_NULL,
                      null=True, blank=True,
                      related_name="subcategories",
                      verbose_name=_("parent category"),
                  )
    sort_order  = models.PositiveIntegerField(default=0, db_index=True)
    is_active   = models.BooleanField(default=True, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Category")
        verbose_name_plural = _("Categories")
        ordering            = ["sort_order", "name"]

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent.name} › {self.name}"
        return self.name


# ---------------------------------------------------------------------------
# Video (core content entity)
# ---------------------------------------------------------------------------

class Video(models.Model):
    """
    Core content entity for the streaming platform.

    A Video can be a standalone movie, a series container, a single course, or
    any episode within a season (Episode model links back to Video for the
    actual media file).

    Access control is enforced via ``access_level``:
    - free    → anyone with an account
    - starter → requires Starter plan or above
    - growth  → requires Growth plan or above
    - pro     → requires Pro plan
    - ppv     → one-time credits purchase required
    """

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    title           = models.CharField(max_length=512, db_index=True)
    slug            = models.SlugField(max_length=512, unique=True, db_index=True)
    description     = models.TextField(blank=True, default="")
    short_description = models.CharField(max_length=256, blank=True, default="")

    # Classification
    content_type    = models.CharField(
                          max_length=20,
                          choices=ContentType.choices,
                          default=ContentType.MOVIE,
                          db_index=True,
                      )
    categories      = models.ManyToManyField(
                          Category,
                          related_name="videos",
                          blank=True,
                      )
    genres          = models.ManyToManyField(
                          Genre,
                          related_name="videos",
                          blank=True,
                      )

    # Access control
    access_level    = models.CharField(
                          max_length=10,
                          choices=AccessLevel.choices,
                          default=AccessLevel.GROWTH,
                          db_index=True,
                          help_text=_("Minimum subscription plan required to watch"),
                      )
    ppv_credits     = models.DecimalField(
                          max_digits=10,
                          decimal_places=2,
                          default=Decimal("0"),
                          help_text=_("Credits charged for pay-per-view access"),
                      )

    # Media assets
    thumbnail       = models.ImageField(
                          upload_to="thumbnails/%Y/%m/",
                          blank=True, null=True,
                      )
    banner_image    = models.ImageField(
                          upload_to="banners/%Y/%m/",
                          blank=True, null=True,
                      )
    trailer_url     = models.URLField(max_length=1024, blank=True, default="")

    # Primary video file (for non-series content)
    video_file_key  = models.CharField(
                          max_length=1024,
                          blank=True, default="",
                          help_text=_("S3 object key for master video file"),
                      )
    hls_manifest_key = models.CharField(
                           max_length=1024,
                           blank=True, default="",
                           help_text=_("S3 key for HLS master playlist (.m3u8)"),
                       )
    duration_seconds = models.PositiveIntegerField(
                           default=0,
                           help_text=_("Total duration in seconds"),
                       )

    # Metadata
    release_year    = models.PositiveSmallIntegerField(null=True, blank=True)
    language        = models.CharField(max_length=32, default="Bengali")
    country         = models.CharField(max_length=64, default="Bangladesh")
    rating          = models.CharField(
                          max_length=10,
                          blank=True, default="",
                          help_text=_("Content rating: G, PG, PG-13, R, etc."),
                      )
    cast            = models.JSONField(
                          default=list, blank=True,
                          help_text=_("List of cast member dicts: {name, role, image_url}"),
                      )
    tags            = models.JSONField(
                          default=list, blank=True,
                          help_text=_("Free-form searchable tags"),
                      )

    # Status & editorial
    status          = models.CharField(
                          max_length=20,
                          choices=ContentStatus.choices,
                          default=ContentStatus.DRAFT,
                          db_index=True,
                      )
    is_featured     = models.BooleanField(default=False, db_index=True)
    is_trending     = models.BooleanField(default=False, db_index=True)
    sort_order      = models.PositiveIntegerField(default=0)

    # Aggregated stats (updated periodically by Celery)
    view_count      = models.PositiveBigIntegerField(default=0)
    avg_rating      = models.DecimalField(
                          max_digits=3, decimal_places=1,
                          default=Decimal("0.0"),
                      )
    rating_count    = models.PositiveIntegerField(default=0)

    # Concurrency limits
    max_concurrent_streams = models.PositiveSmallIntegerField(
                                 default=3,
                                 help_text=_("Max simultaneous streams per user for this content"),
                             )

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    published_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = _("Video")
        verbose_name_plural = _("Videos")
        ordering            = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["content_type", "status"]),
            models.Index(fields=["is_featured", "status"]),
            models.Index(fields=["access_level"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.content_type}, {self.status})"

    @property
    def duration_display(self) -> str:
        """Return formatted duration string like '1h 23m'."""
        if not self.duration_seconds:
            return ""
        hours, remainder = divmod(self.duration_seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def publish(self) -> None:
        self.status = ContentStatus.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at", "updated_at"])


# ---------------------------------------------------------------------------
# VideoQuality
# ---------------------------------------------------------------------------

class VideoQuality(models.Model):
    """
    A specific quality variant of a Video (or Episode).

    Each quality level has its own S3 key for the video segment/HLS playlist,
    bitrate, and file size metadata.
    """

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video           = models.ForeignKey(
                          Video,
                          on_delete=models.CASCADE,
                          related_name="quality_variants",
                      )
    quality         = models.CharField(
                          max_length=10,
                          choices=VideoQualityLabel.choices,
                          default=VideoQualityLabel.Q_720P,
                      )
    video_file_key  = models.CharField(
                          max_length=1024,
                          help_text=_("S3 key for this quality variant"),
                      )
    hls_playlist_key = models.CharField(
                           max_length=1024,
                           blank=True, default="",
                           help_text=_("S3 key for HLS playlist for this quality level"),
                       )
    bitrate_kbps    = models.PositiveIntegerField(
                          default=0,
                          help_text=_("Video bitrate in kbps"),
                      )
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    is_ready        = models.BooleanField(
                          default=False,
                          help_text=_("Set True once encoding is complete"),
                      )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Video Quality Variant")
        verbose_name_plural = _("Video Quality Variants")
        unique_together     = [("video", "quality")]
        ordering            = ["video", "quality"]

    def __str__(self) -> str:
        return f"{self.video.title} — {self.quality}"


# ---------------------------------------------------------------------------
# VideoSubtitle
# ---------------------------------------------------------------------------

class VideoSubtitle(models.Model):
    """Subtitle/caption track for a video."""

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video       = models.ForeignKey(
                      Video,
                      on_delete=models.CASCADE,
                      related_name="subtitles",
                  )
    language    = models.CharField(max_length=32, help_text=_("e.g. 'Bengali', 'English'"))
    language_code = models.CharField(max_length=8, help_text=_("ISO 639-1 code, e.g. 'bn', 'en'"))
    subtitle_key = models.CharField(
                       max_length=1024,
                       help_text=_("S3 key for .vtt or .srt subtitle file"),
                   )
    is_default  = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Video Subtitle")
        verbose_name_plural = _("Video Subtitles")
        unique_together     = [("video", "language_code")]

    def __str__(self) -> str:
        return f"{self.video.title} — {self.language}"


# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------

class Season(models.Model):
    """A season belonging to a series Video."""

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series       = models.ForeignKey(
                       Video,
                       on_delete=models.CASCADE,
                       related_name="seasons",
                       limit_choices_to={"content_type": ContentType.SERIES},
                   )
    season_number = models.PositiveSmallIntegerField()
    title        = models.CharField(max_length=256, blank=True, default="")
    description  = models.TextField(blank=True, default="")
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Season")
        verbose_name_plural = _("Seasons")
        unique_together     = [("series", "season_number")]
        ordering            = ["series", "season_number"]

    def __str__(self) -> str:
        return f"{self.series.title} — S{self.season_number:02d}"


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

class Episode(models.Model):
    """
    A single episode within a Season.

    Each episode has its own Video object that holds the actual media file and
    quality variants, allowing episodes to be managed independently.
    """

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    season          = models.ForeignKey(
                          Season,
                          on_delete=models.CASCADE,
                          related_name="episodes",
                      )
    episode_number  = models.PositiveSmallIntegerField()
    video           = models.OneToOneField(
                          Video,
                          on_delete=models.PROTECT,
                          related_name="episode_detail",
                          help_text=_("Video object containing the episode media"),
                      )
    title           = models.CharField(max_length=512)
    description     = models.TextField(blank=True, default="")
    thumbnail       = models.ImageField(
                          upload_to="episode_thumbnails/%Y/%m/",
                          blank=True, null=True,
                      )
    is_free_preview = models.BooleanField(
                          default=False,
                          help_text=_("Allow non-subscribers to watch this episode"),
                      )
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Episode")
        verbose_name_plural = _("Episodes")
        unique_together     = [("season", "episode_number")]
        ordering            = ["season", "episode_number"]

    def __str__(self) -> str:
        return f"{self.season} — E{self.episode_number:02d}: {self.title}"


# ---------------------------------------------------------------------------
# WatchHistory
# ---------------------------------------------------------------------------

class WatchHistory(models.Model):
    """
    Per-user watch progress for a Video (or episode).

    Enables 'Continue Watching' feature. Position is stored in seconds.
    A record is created on first watch and updated on each progress event.
    """

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user             = models.ForeignKey(
                           User,
                           on_delete=models.CASCADE,
                           related_name="watch_history",
                       )
    video            = models.ForeignKey(
                           Video,
                           on_delete=models.CASCADE,
                           related_name="watch_history",
                       )
    position_seconds = models.PositiveIntegerField(
                           default=0,
                           help_text=_("Last watched position in seconds"),
                       )
    completed        = models.BooleanField(
                           default=False,
                           help_text=_("True if user watched ≥ 90% of the content"),
                       )
    watch_count      = models.PositiveIntegerField(
                           default=1,
                           help_text=_("Number of times fully watched"),
                       )
    last_watched_at  = models.DateTimeField(default=timezone.now, db_index=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("Watch History")
        verbose_name_plural = _("Watch Histories")
        unique_together     = [("user", "video")]
        ordering            = ["-last_watched_at"]
        indexes = [
            models.Index(fields=["user", "-last_watched_at"]),
            models.Index(fields=["user", "completed"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} watched {self.video.title} @ {self.position_seconds}s"

    def update_progress(self, position: int) -> None:
        """Update watch position and mark completed if >= 90% watched."""
        self.position_seconds = position
        if self.video.duration_seconds:
            pct = position / self.video.duration_seconds
            if pct >= 0.90 and not self.completed:
                self.completed = True
                self.watch_count = self.watch_count + 1
        self.last_watched_at = timezone.now()
        self.save(update_fields=["position_seconds", "completed", "watch_count", "last_watched_at"])


# ---------------------------------------------------------------------------
# StreamSession
# ---------------------------------------------------------------------------

class StreamSession(models.Model):
    """
    Tracks an active streaming session for concurrency control.

    When a user starts playback a StreamSession is created.
    The session is kept alive via periodic heartbeats from the player.
    If the number of active sessions exceeds the user's plan limit, the
    oldest session is kicked.

    Session expiry is enforced by a Celery beat task.
    """

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user             = models.ForeignKey(
                           User,
                           on_delete=models.CASCADE,
                           related_name="stream_sessions",
                       )
    video            = models.ForeignKey(
                           Video,
                           on_delete=models.CASCADE,
                           related_name="stream_sessions",
                       )
    device_id        = models.CharField(max_length=255, db_index=True)
    device_type      = models.CharField(max_length=32, blank=True, default="")
    ip_address       = models.GenericIPAddressField(null=True, blank=True)

    # Signed URL info
    signed_url_key   = models.CharField(
                           max_length=1024, blank=True, default="",
                           help_text=_("S3 key the signed URL was generated for"),
                       )
    signed_url_expires_at = models.DateTimeField(
                                null=True, blank=True,
                                help_text=_("When the signed streaming URL expires"),
                            )

    # Quality selected
    quality          = models.CharField(
                           max_length=10,
                           choices=VideoQualityLabel.choices,
                           default=VideoQualityLabel.Q_720P,
                       )

    status           = models.CharField(
                           max_length=10,
                           choices=StreamStatus.choices,
                           default=StreamStatus.ACTIVE,
                           db_index=True,
                       )

    # Heartbeat tracking
    last_heartbeat_at = models.DateTimeField(default=timezone.now, db_index=True)
    heartbeat_count   = models.PositiveIntegerField(default=0)

    # Position when session ended (for watch history sync)
    ended_position_seconds = models.PositiveIntegerField(default=0)

    started_at       = models.DateTimeField(auto_now_add=True)
    ended_at         = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = _("Stream Session")
        verbose_name_plural = _("Stream Sessions")
        ordering            = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "video", "status"]),
            models.Index(fields=["last_heartbeat_at", "status"]),
        ]

    def __str__(self) -> str:
        return f"StreamSession({self.user_id}, {self.video.title}, {self.status})"

    def heartbeat(self, position: int = 0) -> None:
        """Update heartbeat timestamp and optionally position."""
        self.last_heartbeat_at = timezone.now()
        self.heartbeat_count += 1
        if position:
            self.ended_position_seconds = position
        self.save(update_fields=["last_heartbeat_at", "heartbeat_count", "ended_position_seconds"])

    def end(self, position: int = 0) -> None:
        """Mark session as ended."""
        self.status = StreamStatus.ENDED
        self.ended_at = timezone.now()
        if position:
            self.ended_position_seconds = position
        self.save(update_fields=["status", "ended_at", "ended_position_seconds"])


# ---------------------------------------------------------------------------
# VideoRating
# ---------------------------------------------------------------------------

class VideoRating(models.Model):
    """User rating and optional review text for a Video."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
                     User,
                     on_delete=models.CASCADE,
                     related_name="video_ratings",
                 )
    video      = models.ForeignKey(
                     Video,
                     on_delete=models.CASCADE,
                     related_name="ratings",
                 )
    stars      = models.PositiveSmallIntegerField(
                     validators=[MinValueValidator(1), MaxValueValidator(5)],
                     help_text=_("Rating from 1 to 5 stars"),
                 )
    review     = models.TextField(blank=True, default="")
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("Video Rating")
        verbose_name_plural = _("Video Ratings")
        unique_together     = [("user", "video")]
        ordering            = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} rated {self.video.title}: {self.stars}/5"


# ---------------------------------------------------------------------------
# VideoAccessLog
# ---------------------------------------------------------------------------

class VideoAccessLog(models.Model):
    """
    Immutable audit trail for every stream access attempt.

    Used for fraud detection, DMCA compliance, and billing reconciliation.
    """

    class AccessResult(models.TextChoices):
        GRANTED   = "granted",   _("Access Granted")
        DENIED    = "denied",    _("Access Denied — Insufficient Plan")
        EXPIRED   = "expired",   _("Access Denied — Signed URL Expired")
        FRAUD     = "fraud",     _("Blocked — Fraud Detected")

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(
                      User,
                      on_delete=models.SET_NULL,
                      null=True,
                      related_name="video_access_logs",
                  )
    video       = models.ForeignKey(
                      Video,
                      on_delete=models.SET_NULL,
                      null=True,
                      related_name="access_logs",
                  )
    session     = models.ForeignKey(
                      StreamSession,
                      on_delete=models.SET_NULL,
                      null=True, blank=True,
                      related_name="access_logs",
                  )
    result      = models.CharField(
                      max_length=10,
                      choices=AccessResult.choices,
                      db_index=True,
                  )
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    device_id   = models.CharField(max_length=255, blank=True, default="")
    user_agent  = models.TextField(blank=True, default="")
    metadata    = models.JSONField(default=dict, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name        = _("Video Access Log")
        verbose_name_plural = _("Video Access Logs")
        ordering            = ["-created_at"]
        default_permissions = ("view",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["result", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"AccessLog({self.user_id}, {self.result}, {self.created_at:%Y-%m-%d %H:%M})"
