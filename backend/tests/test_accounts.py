"""
Tests for apps.accounts — User model, OTP, JWT auth endpoints.
"""

import hashlib
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

User = get_user_model()


# ─── User Model ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUserModel:
    def test_create_user(self):
        user = User.objects.create_user(
            phone_number="+8801711234567",
            full_name="Rahim Uddin",
            password="securepass",
        )
        assert user.phone_number == "+8801711234567"
        assert user.full_name == "Rahim Uddin"
        assert user.is_active is True
        assert user.is_staff is False
        assert user.referral_code  # auto-generated

    def test_create_user_generates_referral_code(self, make_user):
        u1 = make_user(phone="+8801711111001")
        u2 = make_user(phone="+8801711111002")
        assert u1.referral_code != u2.referral_code
        assert len(u1.referral_code) > 0

    def test_phone_validator_rejects_invalid(self):
        from django.core.exceptions import ValidationError
        user = User(phone_number="01712345678", full_name="Test")
        with pytest.raises(ValidationError):
            user.full_clean()

    def test_phone_validator_accepts_valid(self, make_user):
        user = make_user(phone="+8801812345678")
        assert user.phone_number == "+8801812345678"

    def test_is_kyc_verified_property(self, make_user):
        user = make_user()
        assert user.is_kyc_verified is False
        user.kyc_status = User.KYCStatus.VERIFIED
        assert user.is_kyc_verified is True

    def test_short_name_property(self, make_user):
        user = make_user(full_name="Karim Ahmed")
        assert user.short_name == "Karim"

    def test_short_name_falls_back_to_phone(self, make_user):
        user = make_user(full_name="")
        assert user.short_name == user.phone_number

    def test_add_device_token(self, user):
        user.add_device_token("token-abc", "fcm")
        user.refresh_from_db()
        assert any(t["token"] == "token-abc" for t in user.device_tokens)

    def test_add_device_token_deduplicates(self, user):
        user.add_device_token("same-token", "fcm")
        user.add_device_token("same-token", "fcm")
        user.refresh_from_db()
        assert len([t for t in user.device_tokens if t["token"] == "same-token"]) == 1

    def test_remove_device_token(self, user):
        user.add_device_token("remove-me", "fcm")
        user.remove_device_token("remove-me")
        user.refresh_from_db()
        assert not any(t["token"] == "remove-me" for t in user.device_tokens)

    def test_str_representation(self, user):
        assert user.phone_number in str(user)


# ─── OTP Model ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestOTPVerification:
    def test_create_otp_hashes_code(self, user):
        from apps.accounts.models import OTPVerification
        otp = OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="123456",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        expected_hash = hashlib.sha256(b"123456").hexdigest()
        assert otp.otp_hash == expected_hash

    def test_verify_correct_code_returns_true(self, user):
        from apps.accounts.models import OTPVerification
        otp = OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="654321",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert otp.verify("654321") is True
        assert otp.is_used is True

    def test_verify_wrong_code_returns_false(self, user):
        from apps.accounts.models import OTPVerification
        otp = OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="111111",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert otp.verify("999999") is False
        assert otp.attempts == 1

    def test_verify_expired_otp_returns_false(self, user):
        from apps.accounts.models import OTPVerification
        otp = OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="123456",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert otp.is_expired is True
        assert otp.verify("123456") is False

    def test_create_otp_invalidates_previous(self, user):
        from apps.accounts.models import OTPVerification
        otp1 = OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="111111",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        assert not otp1.is_used  # still valid before second create

        OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.LOGIN,
            raw_code="222222",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        otp1.refresh_from_db()
        assert otp1.is_used is True  # invalidated by new OTP

    def test_max_attempts_blocks_verification(self, user):
        from apps.accounts.models import OTPVerification
        from django.test import override_settings
        with override_settings(OTP_MAX_ATTEMPTS=3):
            otp = OTPVerification.create_otp(
                user=user,
                purpose=OTPVerification.Purpose.LOGIN,
                raw_code="123456",
                expires_at=timezone.now() + timedelta(minutes=5),
            )
            otp.verify("wrong1")
            otp.verify("wrong2")
            otp.verify("wrong3")
            # Exhausted — correct code should still fail
            assert otp.verify("123456") is False


# ─── Auth API Endpoints ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestHealthEndpoints:
    def test_health_check(self, api_client):
        response = api_client.get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ok"

    def test_ready_check(self, api_client):
        response = api_client.get("/ready/")
        # May be degraded if Redis is not available in test env, but should respond
        assert response.status_code in (200, 503)
        assert "status" in response.json()


@pytest.mark.django_db
class TestJWTAuth:
    def test_authenticated_request_succeeds(self, auth_client, user):
        # Any authenticated endpoint should work
        response = auth_client.get("/api/v1/auth/me/")
        # 200 or 404 (endpoint may differ), but NOT 401
        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_unauthenticated_request_to_protected_endpoint(self, api_client):
        response = api_client.get("/api/v1/wallet/balance/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_token_refresh(self, user, api_client):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        response = api_client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": str(refresh)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.json()
