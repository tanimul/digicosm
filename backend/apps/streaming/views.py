"""
Streaming Platform API Views.

Endpoints
---------
GET    /api/v1/streaming/videos/                   VideoListView
GET    /api/v1/streaming/videos/{slug}/            VideoDetailView
GET    /api/v1/streaming/videos/featured/          FeaturedVideosView
GET    /api/v1/streaming/videos/trending/          TrendingVideosView
POST   /api/v1/streaming/play/                     StreamPlayView
POST   /api/v1/streaming/sessions/{id}/heartbeat/  HeartbeatView
POST   /api/v1/streaming/sessions/{id}/end/        EndSessionView
GET    /api/v1/streaming/watch-history/            WatchHistoryListView
PATCH  /api/v1/streaming/watch-history/{id}/progress/ WatchProgressView
GET    /api/v1/streaming/categories/               CategoryListView
GET    /api/v1/streaming/genres/                   GenreListView
POST   /api/v1/streaming/videos/{slug}/rate/       VideoRateView
GET    /api/v1/streaming/videos/{slug}/seasons/    VideoSeasonsView
"""

import logging

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.streaming.models import (
    Category,
    ContentStatus,
    Genre,
    Season,
    StreamSession,
    StreamStatus,
    Video,
    VideoRating,
    WatchHistory,
)
from apps.streaming.serializers import (
    CategorySerializer,
    GenreSerializer,
    HeartbeatSerializer,
    SeasonSerializer,
    StreamRequestSerializer,
    VideoDetailSerializer,
    VideoListSerializer,
    VideoRatingSerializer,
    WatchHistorySerializer,
    WatchProgressUpdateSerializer,
)
from apps.streaming.services import request_stream, update_watch_history

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class VideoPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_ip(request: Request) -> str | None:
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# Video Browse
# ---------------------------------------------------------------------------


class VideoListView(generics.ListAPIView):
    """
    GET /streaming/videos/
    List published videos with optional filtering.

    Query params: content_type, access_level, category, genre, search
    """

    serializer_class = VideoListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = VideoPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "tags"]
    ordering_fields = ["published_at", "view_count", "avg_rating", "sort_order"]
    ordering = ["-published_at"]

    def get_queryset(self):
        qs = (
            Video.objects.filter(status=ContentStatus.PUBLISHED)
            .prefetch_related("genres", "categories")
        )
        content_type = self.request.query_params.get("content_type")
        if content_type:
            qs = qs.filter(content_type=content_type)

        access_level = self.request.query_params.get("access_level")
        if access_level:
            qs = qs.filter(access_level=access_level)

        category_slug = self.request.query_params.get("category")
        if category_slug:
            qs = qs.filter(categories__slug=category_slug)

        genre_slug = self.request.query_params.get("genre")
        if genre_slug:
            qs = qs.filter(genres__slug=genre_slug)

        return qs.distinct()


class VideoDetailView(generics.RetrieveAPIView):
    """GET /streaming/videos/{slug}/"""

    serializer_class = VideoDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"
    queryset = Video.objects.filter(status=ContentStatus.PUBLISHED).prefetch_related(
        "genres", "categories", "quality_variants", "subtitles"
    )


class FeaturedVideosView(generics.ListAPIView):
    """GET /streaming/videos/featured/"""

    serializer_class = VideoListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = VideoPagination

    def get_queryset(self):
        return (
            Video.objects.filter(status=ContentStatus.PUBLISHED, is_featured=True)
            .prefetch_related("genres", "categories")
            .order_by("sort_order", "-published_at")
        )


class TrendingVideosView(generics.ListAPIView):
    """GET /streaming/videos/trending/"""

    serializer_class = VideoListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = VideoPagination

    def get_queryset(self):
        return (
            Video.objects.filter(status=ContentStatus.PUBLISHED, is_trending=True)
            .prefetch_related("genres", "categories")
            .order_by("-view_count", "-published_at")
        )


class VideoSeasonsView(generics.ListAPIView):
    """GET /streaming/videos/{slug}/seasons/ — list seasons+episodes for a series."""

    serializer_class = SeasonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        video = get_object_or_404(Video, slug=self.kwargs["slug"], status=ContentStatus.PUBLISHED)
        return Season.objects.filter(series=video, is_active=True).prefetch_related(
            "episodes__video__quality_variants",
            "episodes__video__subtitles",
        )


# ---------------------------------------------------------------------------
# Streaming Session
# ---------------------------------------------------------------------------


class StreamPlayView(APIView):
    """
    POST /streaming/play/
    Request a signed streaming URL. Creates a StreamSession.

    Body: { video_id, quality, device_id, device_type }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = StreamRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        video = get_object_or_404(Video, id=data["video_id"], status=ContentStatus.PUBLISHED)
        ip = _get_ip(request)

        try:
            result = request_stream(
                user=request.user,
                video=video,
                device_id=data["device_id"],
                quality=data.get("quality", "720p"),
                device_type=data.get("device_type", "web"),
                ip_address=ip,
            )
        except ValidationError as exc:
            return Response(
                {"success": False, "error": exc.message, "code": exc.code},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response({"success": True, "data": result}, status=status.HTTP_200_OK)


class HeartbeatView(APIView):
    """
    POST /streaming/sessions/{session_id}/heartbeat/
    Keep-alive ping from the player. Body: { position_seconds }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, session_id: str) -> Response:
        session = get_object_or_404(
            StreamSession,
            id=session_id,
            user=request.user,
            status=StreamStatus.ACTIVE,
        )
        serializer = HeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session.heartbeat(position=serializer.validated_data.get("position_seconds", 0))
        return Response({"success": True, "message": "heartbeat recorded"})


class EndSessionView(APIView):
    """
    POST /streaming/sessions/{session_id}/end/
    End a streaming session. Body: { position_seconds }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, session_id: str) -> Response:
        session = get_object_or_404(
            StreamSession,
            id=session_id,
            user=request.user,
            status=StreamStatus.ACTIVE,
        )
        position = request.data.get("position_seconds", 0)
        session.end(position=position)

        # Sync watch history
        update_watch_history(request.user, session.video, position)
        return Response({"success": True, "message": "session ended"})


# ---------------------------------------------------------------------------
# Watch History
# ---------------------------------------------------------------------------


class WatchHistoryListView(generics.ListAPIView):
    """GET /streaming/watch-history/ — current user's watch history."""

    serializer_class = WatchHistorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = VideoPagination

    def get_queryset(self):
        return (
            WatchHistory.objects.filter(user=self.request.user)
            .select_related("video")
            .order_by("-last_watched_at")
        )


class WatchProgressView(APIView):
    """PATCH /streaming/watch-history/{id}/progress/ — update position."""

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, pk: str) -> Response:
        history = get_object_or_404(WatchHistory, id=pk, user=request.user)
        serializer = WatchProgressUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        history.update_progress(serializer.validated_data["position_seconds"])
        return Response({"success": True, "position_seconds": history.position_seconds})


# ---------------------------------------------------------------------------
# Catalogue: Categories & Genres
# ---------------------------------------------------------------------------


class CategoryListView(generics.ListAPIView):
    """GET /streaming/categories/"""

    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    queryset = Category.objects.filter(is_active=True).order_by("sort_order", "name")


class GenreListView(generics.ListAPIView):
    """GET /streaming/genres/"""

    serializer_class = GenreSerializer
    permission_classes = [IsAuthenticated]
    queryset = Genre.objects.filter(is_active=True).order_by("name")


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------


class VideoRateView(APIView):
    """
    POST /streaming/videos/{slug}/rate/
    Create or update a user rating for a video.
    Body: { stars, review }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, slug: str) -> Response:
        video = get_object_or_404(Video, slug=slug, status=ContentStatus.PUBLISHED)
        existing = VideoRating.objects.filter(user=request.user, video=video).first()

        serializer = VideoRatingSerializer(
            instance=existing,
            data={**request.data, "video": str(video.id)},
            partial=bool(existing),
        )
        serializer.is_valid(raise_exception=True)

        if existing:
            serializer.save()
            return Response({"success": True, "data": serializer.data})

        serializer.save(user=request.user, video=video)

        # Trigger async rating aggregate recalculation
        try:
            from apps.streaming.tasks import recalculate_video_rating
            recalculate_video_rating.delay(str(video.id))
        except Exception:
            pass

        return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
