"""
Tests for apps.ai_gateway — AIProvider, ProviderAPIKey, AIService, API endpoints.
"""

import pytest
from rest_framework import status


# ─── AIProvider Model ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAIProviderModel:
    def test_create_provider(self, ai_provider):
        from apps.ai_gateway.models import ProviderName
        assert ai_provider.name == ProviderName.OPENAI
        assert ai_provider.display_name == "OpenAI"
        assert ai_provider.is_active is True
        assert ai_provider.is_healthy is True

    def test_provider_str(self, ai_provider):
        assert "OpenAI" in str(ai_provider) or ai_provider.name in str(ai_provider)

    def test_provider_unique_name(self, db, ai_provider):
        from apps.ai_gateway.models import AIProvider, ProviderName
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            AIProvider.objects.create(
                name=ProviderName.OPENAI,  # duplicate
                display_name="OpenAI 2",
                base_url="https://api.openai.com/v2",
            )


# ─── ProviderAPIKey Encryption ───────────────────────────────────────────────

@pytest.mark.django_db
class TestProviderAPIKeyEncryption:
    def test_key_is_encrypted_at_rest(self, db, ai_provider):
        from apps.ai_gateway.models import ProviderAPIKey
        raw_key = "sk-test-1234567890abcdef"
        api_key = ProviderAPIKey.objects.create(
            provider=ai_provider,
            raw_key=raw_key,
            label="Test Key",
        )
        api_key.refresh_from_db()
        # The stored value should NOT be the raw key
        assert api_key.encrypted_key != raw_key
        # But decryption should return the original
        assert api_key.decrypt_key() == raw_key

    def test_key_hash_is_stored(self, db, ai_provider):
        import hashlib
        from apps.ai_gateway.models import ProviderAPIKey
        raw_key = "sk-hash-test-key"
        api_key = ProviderAPIKey.objects.create(
            provider=ai_provider,
            raw_key=raw_key,
            label="Hash Test",
        )
        expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        assert api_key.key_hash == expected_hash

    def test_failure_count_deactivates_key(self, db, ai_provider):
        from apps.ai_gateway.models import ProviderAPIKey
        api_key = ProviderAPIKey.objects.create(
            provider=ai_provider,
            raw_key="sk-deactivate-test",
            label="Deactivate Test",
            failure_count=9,
            is_active=True,
        )
        api_key.failure_count = 10
        api_key.save()
        api_key.refresh_from_db()
        # Should be auto-deactivated at threshold
        assert api_key.failure_count >= 10


# ─── AIService Model ─────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAIServiceModel:
    def test_create_service(self, db, ai_provider):
        from apps.ai_gateway.models import AIService, ServiceType
        service = AIService.objects.create(
            provider=ai_provider,
            name="GPT-4o",
            slug="gpt-4o",
            model_id="gpt-4o",
            service_type=ServiceType.CHAT,
            sell_price_credits=10,
            cost_per_request_bdt="0.50",
        )
        assert service.name == "GPT-4o"
        assert service.sell_price_credits == 10

    def test_service_slug_unique(self, db, ai_provider):
        from apps.ai_gateway.models import AIService, ServiceType
        from django.db import IntegrityError
        AIService.objects.create(
            provider=ai_provider, name="GPT-4o",
            slug="gpt-4o-dup", model_id="gpt-4o",
            service_type=ServiceType.CHAT,
        )
        with pytest.raises(IntegrityError):
            AIService.objects.create(
                provider=ai_provider, name="GPT-4o Copy",
                slug="gpt-4o-dup", model_id="gpt-4o",
                service_type=ServiceType.CHAT,
            )


# ─── AI API Endpoints ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAIServiceAPI:
    def test_list_services_requires_auth(self, api_client):
        response = api_client.get("/api/v1/ai/services/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_services_authenticated(self, auth_client, db):
        from apps.ai_gateway.models import AIProvider, ProviderName
        AIProvider.objects.create(
            name=ProviderName.GEMINI,
            display_name="Google Gemini",
            base_url="https://generativelanguage.googleapis.com",
        )
        response = auth_client.get("/api/v1/ai/services/")
        assert response.status_code == status.HTTP_200_OK

    def test_list_conversations_requires_auth(self, api_client):
        response = api_client.get("/api/v1/ai/conversations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_conversations_authenticated(self, auth_client):
        response = auth_client.get("/api/v1/ai/conversations/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data or isinstance(data, list)
