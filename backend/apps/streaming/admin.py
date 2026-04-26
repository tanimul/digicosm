"""
Streaming Platform Django Admin Configuration.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Category,
    Episode,
    Genre,
    Season,
    StreamSession,
    Video,
    VideoAccessLog,
    VideoQuality,
    VideoRating,
    VideoSubtitle,
    WatchHistory,
)


# ---------------------------------------------------------------------------
# Genre & Category
# ---------------------------------------------------------------------------


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "icon", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "parent", "sort_order", "is_active"]
    list_filter = ["is_active", "parent"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["sort_order", "name"]


# ---------------------------------------------------------------------------
# Video (with inlines)
# ---------------------------------------------------------------------------


class VideoQualityInline(admin.TabularInline):
    model = VideoQuality
    extra = 0
    fields = ["quality", "video_file_key", "hls_playlist_key", "bitrate_kbps", "file_size_bytes", "is_ready"]


class VideoSubtitleInline(admin.TabularInline):
    model = VideoSubtitle
    extra = 0
    fields = ["language", "language_code", "subtitle_key", "is_default"]


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = [
        "title", "content_type", "access_level", "status",
        "is_featured", "is_trending", "view_count", "avg_rating",
        "published_at",
    ]
    list_filter = ["content_type", "status", "access_level", "is_featured", "is_trending", "language"]
    search_fields = ["title", "slug", "description", "tags"]
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ["categories", "genres"]
    readonly_fields = ["view_count", "avg_rating", "rating_count", "created_at", "updated_at"]
    inlines = [VideoQualityInline, VideoSubtitleInline]
    actions = ["publish_selected", "archive_selected"]
    ordering = ["-created_at"]

    fieldsets = [
        ("Identity", {
            "fields": ["title", "slug", "description", "short_description"],
        }),
        ("Classification", {
            "fields": ["content_type", "categories", "genres", "rating", "language", "country", "release_year"],
        }),
        ("Access Control", {
            "fields": ["access_level", "ppv_credits", "max_concurrent_streams"],
        }),
        ("Media", {
            "fields": ["thumbnail", "banner_image", "trailer_url", "video_file_key", "hls_manifest_key", "duration_seconds"],
        }),
        ("Editorial", {
            "fields": ["status", "is_featured", "is_trending", "sort_order", "published_at"],
        }),
        ("Stats (read-only)", {
            "fields": ["view_count", "avg_rating", "rating_count"],
            "classes": ["collapse"],
        }),
        ("Metadata", {
            "fields": ["cast", "tags", "created_at", "updated_at"],
            "classes": ["collapse"],
        }),
    ]

    def publish_selected(self, request, queryset):
        for video in queryset:
            video.publish()
    publish_selected.short_description = "Publish selected videos"

    def archive_selected(self, request, queryset):
        from .models import ContentStatus
        queryset.update(status=ContentStatus.ARCHIVED)
    archive_selected.short_description = "Archive selected videos"


# ---------------------------------------------------------------------------
# Season & Episode
# ---------------------------------------------------------------------------


class EpisodeInline(admin.TabularInline):
    model = Episode
    extra = 0
    fields = ["episode_number", "title", "video", "is_free_preview"]
    raw_id_fields = ["video"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["__str__", "series", "season_number", "is_active", "release_year"]
    list_filter = ["is_active"]
    search_fields = ["title", "series__title"]
    inlines = [EpisodeInline]


# ---------------------------------------------------------------------------
# Stream Session
# ---------------------------------------------------------------------------


@admin.register(StreamSession)
class StreamSessionAdmin(admin.ModelAdmin):
    list_display = [
        "id", "user", "video_title", "device_type", "quality",
        "status", "last_heartbeat_at", "started_at",
    ]
    list_filter = ["status", "quality", "device_type"]
    search_fields = ["user__phone_number", "device_id"]
    readonly_fields = ["id", "started_at", "ended_at", "last_heartbeat_at", "heartbeat_count"]
    raw_id_fields = ["user", "video"]

    def video_title(self, obj):
        return obj.video.title if obj.video_id else "—"
    video_title.short_description = "Video"


# ---------------------------------------------------------------------------
# Watch History
# ---------------------------------------------------------------------------


@admin.register(WatchHistory)
class WatchHistoryAdmin(admin.ModelAdmin):
    list_display = ["user", "video_title", "position_seconds", "completed", "last_watched_at"]
    list_filter = ["completed"]
    search_fields = ["user__phone_number"]
    raw_id_fields = ["user", "video"]

    def video_title(self, obj):
        return obj.video.title if obj.video_id else "—"
    video_title.short_description = "Video"


# ---------------------------------------------------------------------------
# Video Rating
# ---------------------------------------------------------------------------


@admin.register(VideoRating)
class VideoRatingAdmin(admin.ModelAdmin):
    list_display = ["user", "video_title", "stars", "is_visible", "created_at"]
    list_filter = ["stars", "is_visible"]
    search_fields = ["user__phone_number", "review"]
    raw_id_fields = ["user", "video"]

    def video_title(self, obj):
        return obj.video.title if obj.video_id else "—"
    video_title.short_description = "Video"


# ---------------------------------------------------------------------------
# Access Log
# ---------------------------------------------------------------------------


@admin.register(VideoAccessLog)
class VideoAccessLogAdmin(admin.ModelAdmin):
    list_display = ["user", "video_title", "result", "ip_address", "device_id", "created_at"]
    list_filter = ["result"]
    search_fields = ["user__phone_number", "ip_address", "device_id"]
    readonly_fields = [f.name for f in VideoAccessLog._meta.fields]

    def video_title(self, obj):
        return obj.video.title if obj.video_id else "—"
    video_title.short_description = "Video"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
