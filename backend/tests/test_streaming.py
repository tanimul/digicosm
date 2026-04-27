"""
Tests for apps.streaming — Genre, Category, Video models and API endpoints.
"""

import pytest
from rest_framework import status


# ─── Genre Model ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGenreModel:
    def test_create_genre(self, genre):
        assert genre.name == "Action"
        assert genre.slug == "action"
        assert genre.is_active is True

    def test_genre_str(self, genre):
        assert "Action" in str(genre)

    def test_genre_slug_unique(self, db, genre):
        from apps.streaming.models import Genre
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            Genre.objects.create(name="Action 2", slug="action")  # duplicate slug


# ─── Category Model ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCategoryModel:
    def test_create_category(self, db):
        from apps.streaming.models import Category
        cat = Category.objects.create(name="Movies", slug="movies")
        assert cat.name == "Movies"
        assert cat.parent is None

    def test_subcategory(self, db):
        from apps.streaming.models import Category
        parent = Category.objects.create(name="Movies", slug="movies-parent")
        child = Category.objects.create(
            name="Bollywood", slug="bollywood", parent=parent
        )
        assert child.parent == parent
        assert "Movies" in str(child)


# ─── Video Model ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestVideoModel:
    def test_create_video(self, video):
        from apps.streaming.models import ContentType, ContentStatus, AccessLevel
        assert video.title == "Test Movie"
        assert video.content_type == ContentType.MOVIE
        assert video.status == ContentStatus.PUBLISHED
        assert video.access_level == AccessLevel.FREE

    def test_video_str(self, video):
        assert "Test Movie" in str(video)

    def test_video_slug_unique(self, db, genre):
        from apps.streaming.models import Video, ContentType, ContentStatus, AccessLevel
        from django.db import IntegrityError
        Video.objects.create(
            title="Dup Movie", slug="dup-slug",
            content_type=ContentType.MOVIE,
            status=ContentStatus.PUBLISHED,
            access_level=AccessLevel.FREE,
        )
        with pytest.raises(IntegrityError):
            Video.objects.create(
                title="Dup Movie 2", slug="dup-slug",
                content_type=ContentType.MOVIE,
                status=ContentStatus.PUBLISHED,
                access_level=AccessLevel.FREE,
            )

    def test_free_content_accessible_without_subscription(self, video):
        assert video.access_level == "free"

    def test_published_video_in_queryset(self, db, video):
        from apps.streaming.models import Video, ContentStatus
        published = Video.objects.filter(status=ContentStatus.PUBLISHED)
        assert video in published


# ─── Streaming API Endpoints ──────────────────────────────────────────────────

@pytest.mark.django_db
class TestStreamingAPI:
    def test_list_content_requires_auth(self, api_client):
        response = api_client.get("/api/v1/streaming/content/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_content_authenticated(self, auth_client, video):
        response = auth_client.get("/api/v1/streaming/content/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data

    def test_get_content_detail(self, auth_client, video):
        response = auth_client.get(f"/api/v1/streaming/content/{video.slug}/")
        assert response.status_code == status.HTTP_200_OK

    def test_list_genres_authenticated(self, auth_client, genre):
        response = auth_client.get("/api/v1/streaming/genres/")
        assert response.status_code == status.HTTP_200_OK

    def test_filter_content_by_type(self, auth_client, video):
        response = auth_client.get("/api/v1/streaming/content/?content_type=movie")
        assert response.status_code == status.HTTP_200_OK

    def test_search_content(self, auth_client, video):
        response = auth_client.get("/api/v1/streaming/content/?search=Test")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] >= 1
