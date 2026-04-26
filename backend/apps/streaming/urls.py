"""
Streaming Platform URL Configuration.

All routes are prefixed with /api/v1/streaming/ in the root urls.py.

Route summary
-------------
GET  /videos/                          List published videos (filterable)
GET  /videos/featured/                 Featured content
GET  /videos/trending/                 Trending content
GET  /videos/{slug}/                   Video detail
GET  /videos/{slug}/seasons/           Series seasons + episodes
POST /videos/{slug}/rate/              Rate a video
POST /play/                            Request signed streaming URL
POST /sessions/{id}/heartbeat/         Player keep-alive
POST /sessions/{id}/end/               End a stream session
GET  /watch-history/                   Current user watch history
PATCH /watch-history/{id}/progress/    Update watch position
GET  /categories/                      Content categories
GET  /genres/                          Content genres
"""

from django.urls import path

from .views import (
    CategoryListView,
    EndSessionView,
    FeaturedVideosView,
    GenreListView,
    HeartbeatView,
    StreamPlayView,
    TrendingVideosView,
    VideoDetailView,
    VideoListView,
    VideoRateView,
    VideoSeasonsView,
    WatchHistoryListView,
    WatchProgressView,
)

app_name = "streaming"

urlpatterns = [
    # -------------------------------------------------------------------------
    # Video catalogue
    # -------------------------------------------------------------------------
    path("videos/", VideoListView.as_view(), name="video-list"),
    path("videos/featured/", FeaturedVideosView.as_view(), name="video-featured"),
    path("videos/trending/", TrendingVideosView.as_view(), name="video-trending"),
    path("videos/<slug:slug>/", VideoDetailView.as_view(), name="video-detail"),
    path("videos/<slug:slug>/seasons/", VideoSeasonsView.as_view(), name="video-seasons"),
    path("videos/<slug:slug>/rate/", VideoRateView.as_view(), name="video-rate"),
    # -------------------------------------------------------------------------
    # Streaming sessions
    # -------------------------------------------------------------------------
    path("play/", StreamPlayView.as_view(), name="stream-play"),
    path(
        "sessions/<uuid:session_id>/heartbeat/",
        HeartbeatView.as_view(),
        name="session-heartbeat",
    ),
    path(
        "sessions/<uuid:session_id>/end/",
        EndSessionView.as_view(),
        name="session-end",
    ),
    # -------------------------------------------------------------------------
    # Watch history
    # -------------------------------------------------------------------------
    path("watch-history/", WatchHistoryListView.as_view(), name="watch-history-list"),
    path(
        "watch-history/<uuid:pk>/progress/",
        WatchProgressView.as_view(),
        name="watch-history-progress",
    ),
    # -------------------------------------------------------------------------
    # Catalogue metadata
    # -------------------------------------------------------------------------
    path("categories/", CategoryListView.as_view(), name="category-list"),
    path("genres/", GenreListView.as_view(), name="genre-list"),
]
