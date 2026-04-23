"""
Streaming Platform Serializers.
"""

from rest_framework import serializers

from apps.streaming.models import (
    Category,
    Episode,
    Genre,
    Season,
    StreamSession,
    Video,
    VideoQuality,
    VideoRating,
    VideoSubtitle,
    WatchHistory,
)


# ---------------------------------------------------------------------------
# Genre & Category
# ---------------------------------------------------------------------------

class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ["id", "name", "slug", "icon"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "thumbnail", "parent", "sort_order"]


# ---------------------------------------------------------------------------
# Video Quality & Subtitle
# ---------------------------------------------------------------------------

class VideoQualitySerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoQuality
        fields = ["id", "quality", "bitrate_kbps", "file_size_bytes", "is_ready"]


class VideoSubtitleSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoSubtitle
        fields = ["id", "language", "language_code", "is_default"]


# ---------------------------------------------------------------------------
# Video — List & Detail
# ---------------------------------------------------------------------------

class VideoListSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    categories = CategorySerializer(many=True, read_only=True)

    class Meta:
        model = Video
        fields = [
            "id", "title", "slug", "short_description", "content_type",
            "thumbnail", "duration_seconds", "duration_display",
            "access_level", "ppv_credits", "release_year", "language",
            "rating", "is_featured", "is_trending", "avg_rating",
            "rating_count", "view_count", "genres", "categories",
            "published_at",
        ]


class VideoDetailSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    categories = CategorySerializer(many=True, read_only=True)
    quality_variants = VideoQualitySerializer(many=True, read_only=True)
    subtitles = VideoSubtitleSerializer(many=True, read_only=True)

    class Meta:
        model = Video
        fields = [
            "id", "title", "slug", "description", "short_description",
            "content_type", "thumbnail", "banner_image", "trailer_url",
            "duration_seconds", "duration_display", "access_level",
            "ppv_credits", "release_year", "language", "country",
            "rating", "cast", "tags", "is_featured", "is_trending",
            "avg_rating", "rating_count", "view_count",
            "genres", "categories", "quality_variants", "subtitles",
            "published_at", "created_at",
        ]


# ---------------------------------------------------------------------------
# Season & Episode
# ---------------------------------------------------------------------------

class EpisodeSerializer(serializers.ModelSerializer):
    video = VideoDetailSerializer(read_only=True)

    class Meta:
        model = Episode
        fields = [
            "id", "episode_number", "title", "description",
            "thumbnail", "is_free_preview", "video",
        ]


class SeasonSerializer(serializers.ModelSerializer):
    episodes = EpisodeSerializer(many=True, read_only=True)

    class Meta:
        model = Season
        fields = [
            "id", "season_number", "title", "description",
            "release_year", "episodes",
        ]


# ---------------------------------------------------------------------------
# Watch History
# ---------------------------------------------------------------------------

class WatchHistorySerializer(serializers.ModelSerializer):
    video = VideoListSerializer(read_only=True)
    video_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = WatchHistory
        fields = [
            "id", "video", "video_id", "position_seconds",
            "completed", "watch_count", "last_watched_at",
        ]
        read_only_fields = ["id", "completed", "watch_count", "last_watched_at"]


class WatchProgressUpdateSerializer(serializers.Serializer):
    """Used for PATCH /watch-history/{id}/progress/"""
    position_seconds = serializers.IntegerField(min_value=0)


# ---------------------------------------------------------------------------
# Stream Session
# ---------------------------------------------------------------------------

class StreamSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreamSession
        fields = [
            "id", "video", "device_id", "device_type",
            "quality", "status", "started_at",
        ]
        read_only_fields = ["id", "status", "started_at"]


class StreamRequestSerializer(serializers.Serializer):
    """
    Input for POST /stream/play/ — requests a signed streaming URL.
    """
    video_id  = serializers.UUIDField()
    quality   = serializers.ChoiceField(
                    choices=VideoQuality.quality.field.choices if hasattr(VideoQuality, 'quality') else [
                        ("360p", "360p"), ("480p", "480p"), ("720p", "720p"),
                        ("1080p", "1080p"), ("4k", "4k"),
                    ],
                    default="720p",
                )
    device_id = serializers.CharField(max_length=255)
    device_type = serializers.CharField(max_length=32, default="web")


class StreamResponseSerializer(serializers.Serializer):
    """Response for stream play endpoint."""
    session_id   = serializers.UUIDField()
    signed_url   = serializers.URLField()
    expires_at   = serializers.DateTimeField()
    quality      = serializers.CharField()
    subtitles    = VideoSubtitleSerializer(many=True)


class HeartbeatSerializer(serializers.Serializer):
    position_seconds = serializers.IntegerField(min_value=0, default=0)


# ---------------------------------------------------------------------------
# Video Rating
# ---------------------------------------------------------------------------

class VideoRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoRating
        fields = ["id", "video", "stars", "review", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_stars(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("Stars must be between 1 and 5.")
        return value
