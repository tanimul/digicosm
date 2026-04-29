"""
Serializers for the accounts application.

Serializers
-----------
UserRegistrationSerializer   — New user sign-up
OTPVerificationSerializer    — Verify a 6-digit OTP
LoginSerializer              — Phone + password login
UserProfileSerializer        — Read-only user profile representation
UserProfileUpdateSerializer  — Partial update of the user profile
ChangePasswordSerializer     — Authenticated password change
"""

import logging
import re

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import OTPVerification, User, UserDevice
from apps.accounts.utils import normalise_phone_number

logger = logging.getLogger(__name__)

BANGLADESH_PHONE_REGEX = r"^\+880[1-9]\d{9}$"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_bangladesh_phone(value: str) -> str:
    """Normalise then validate a Bangladesh phone number."""
    try:
        value = normalise_phone_number(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from exc

    if not re.match(BANGLADESH_PHONE_REGEX, value):
        raise serializers.ValidationError(
            _("Enter a valid Bangladesh mobile number (+8801XXXXXXXXX).")
        )
    return value


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class UserRegistrationSerializer(serializers.Serializer):
    """
    Handle new user registration.

    The account is created in an unverified state; the caller must
    subsequently request and verify an OTP to activate the account.
    """

    phone_number = serializers.CharField(
        max_length=15,
        help_text=_("Bangladesh mobile number, e.g. +8801712345678"),
    )
    full_name = serializers.CharField(
        max_length=150,
        help_text=_("User's full name"),
    )
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        help_text=_("Minimum 8 characters"),
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    referral_code = serializers.CharField(
        max_length=16,
        required=False,
        allow_blank=True,
        help_text=_("Optional referral code from an existing user"),
    )

    def validate_phone_number(self, value: str) -> str:
        value = _validate_bangladesh_phone(value)
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError(
                _("An account with this phone number already exists.")
            )
        return value

    def validate_password(self, value: str) -> str:
        validate_password(value)
        return value

    def validate_referral_code(self, value: str) -> str | None:
        if not value:
            return None
        try:
            User.objects.get(referral_code=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(_("Invalid referral code."))
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs.pop("confirm_password"):
            raise serializers.ValidationError(
                {"confirm_password": _("Passwords do not match.")}
            )
        return attrs

    def create(self, validated_data: dict) -> User:
        referral_code = validated_data.pop("referral_code", None)

        referred_by: User | None = None
        if referral_code:
            try:
                referred_by = User.objects.get(referral_code=referral_code)
            except User.DoesNotExist:
                pass  # already validated; edge-case guard

        user = User.objects.create_user(
            phone_number=validated_data["phone_number"],
            full_name=validated_data["full_name"],
            password=validated_data["password"],
            referred_by=referred_by,
        )
        return user


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------


class SendOTPSerializer(serializers.Serializer):
    """Request body for sending an OTP to a phone number."""

    phone_number = serializers.CharField(max_length=15)
    purpose = serializers.ChoiceField(choices=OTPVerification.Purpose.choices)

    def validate_phone_number(self, value: str) -> str:
        return _validate_bangladesh_phone(value)

    def validate(self, attrs: dict) -> dict:
        phone_number = attrs["phone_number"]
        purpose = attrs["purpose"]

        # For non-registration purposes, the user must already exist
        if purpose != OTPVerification.Purpose.REGISTER:
            try:
                attrs["user"] = User.objects.get(
                    phone_number=phone_number, is_active=True
                )
            except User.DoesNotExist:
                raise serializers.ValidationError(
                    {"phone_number": _("No active account found for this number.")}
                )

        return attrs


class OTPVerificationSerializer(serializers.Serializer):
    """Verify a 6-digit OTP submitted by the user."""

    phone_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(
        min_length=6,
        max_length=6,
        help_text=_("6-digit numeric OTP sent via SMS"),
    )
    purpose = serializers.ChoiceField(choices=OTPVerification.Purpose.choices)

    def validate_phone_number(self, value: str) -> str:
        return _validate_bangladesh_phone(value)

    def validate_otp_code(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(_("OTP must contain only digits."))
        return value

    def validate(self, attrs: dict) -> dict:
        phone_number = attrs["phone_number"]
        purpose = attrs["purpose"]

        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"phone_number": _("No account found for this phone number.")}
            )

        # Retrieve the most recent valid (unused, unexpired) OTP for this user+purpose
        otp_record = (
            OTPVerification.objects.filter(
                user=user,
                purpose=purpose,
                is_used=False,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

        if otp_record is None:
            raise serializers.ValidationError(
                {"otp_code": _("No valid OTP found. Please request a new one.")}
            )

        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        if otp_record.attempts >= max_attempts:
            raise serializers.ValidationError(
                {
                    "otp_code": _(
                        "Too many failed attempts. Please request a new OTP."
                    )
                }
            )

        attrs["otp_record"] = otp_record
        attrs["user"] = user
        return attrs


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class LoginSerializer(serializers.Serializer):
    """Authenticate a user with phone number + password and return JWT tokens."""

    phone_number = serializers.CharField(max_length=15)
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    device_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        help_text=_("Optional device identifier for session tracking"),
    )
    device_type = serializers.ChoiceField(
        choices=UserDevice.DeviceType.choices,
        required=False,
        default=UserDevice.DeviceType.MOBILE_ANDROID,
    )
    push_token = serializers.CharField(
        max_length=512,
        required=False,
        allow_blank=True,
        help_text=_("FCM / APNs push notification token"),
    )

    def validate_phone_number(self, value: str) -> str:
        return _validate_bangladesh_phone(value)

    def validate(self, attrs: dict) -> dict:
        phone_number = attrs.get("phone_number")
        password = attrs.get("password")

        user = authenticate(
            request=self.context.get("request"),
            username=phone_number,
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                _("Invalid phone number or password.")
            )

        if not user.is_active:
            raise serializers.ValidationError(
                _("This account has been disabled. Please contact support.")
            )

        if not user.is_verified:
            raise serializers.ValidationError(
                _("Phone number not verified. Please complete OTP verification.")
            )

        attrs["user"] = user
        return attrs

    def get_tokens(self, user: User) -> dict[str, str]:
        """Generate and return JWT token pair for the given user."""
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------


class UserProfileSerializer(serializers.ModelSerializer):
    """Read-only serializer for the user profile."""

    avatar_url = serializers.SerializerMethodField()
    is_kyc_verified = serializers.BooleanField(read_only=True)
    referral_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone_number",
            "email",
            "full_name",
            "avatar",
            "avatar_url",
            "is_verified",
            "kyc_status",
            "is_kyc_verified",
            "referral_code",
            "referral_count",
            "date_joined",
            "last_login",
            "last_login_ip",
        ]
        read_only_fields = fields  # all fields read-only in this serializer

    def get_avatar_url(self, obj: User) -> str | None:
        request = self.context.get("request")
        if obj.avatar and request:
            return request.build_absolute_uri(obj.avatar.url)
        return None

    def get_referral_count(self, obj: User) -> int:
        return obj.referrals.filter(is_active=True).count()


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Partial-update serializer for the user profile.

    Phone number and sensitive fields are excluded — they require
    dedicated OTP-protected endpoints.
    """

    avatar = serializers.ImageField(
        required=False,
        allow_null=True,
        help_text=_("Upload a new profile picture (JPEG/PNG, max 5 MB)"),
    )

    class Meta:
        model = User
        fields = [
            "full_name",
            "email",
            "avatar",
        ]

    def validate_email(self, value: str | None) -> str | None:
        if not value:
            return value
        # Ensure email uniqueness, excluding the current user
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                _("This email address is already in use.")
            )
        return value.lower()

    def validate_avatar(self, value):
        if value:
            max_size = 5 * 1024 * 1024  # 5 MB
            if value.size > max_size:
                raise serializers.ValidationError(
                    _("Avatar file size must be under 5 MB.")
                )
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            if hasattr(value, "content_type") and value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    _("Only JPEG, PNG, and WebP images are allowed.")
                )
        return value

    def update(self, instance: User, validated_data: dict) -> User:
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(update_fields=list(validated_data.keys()))
        return instance


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


class ChangePasswordSerializer(serializers.Serializer):
    """Authenticated password change (requires current password)."""

    current_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )
    confirm_new_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_current_password(self, value: str) -> str:
        user: User = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value

    def validate_new_password(self, value: str) -> str:
        validate_password(value, user=self.context["request"].user)
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": _("New passwords do not match.")}
            )
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": _("New password must differ from current password.")}
            )
        return attrs

    def save(self, **kwargs) -> User:
        user: User = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


# ---------------------------------------------------------------------------
# Token serializers
# ---------------------------------------------------------------------------


class TokenRefreshResponseSerializer(serializers.Serializer):
    """Response shape for a successful token refresh."""

    access = serializers.CharField(read_only=True)


class LogoutSerializer(serializers.Serializer):
    """Request body for logout — blacklists the refresh token."""

    refresh = serializers.CharField(
        help_text=_("The refresh token to blacklist"),
    )

    def validate_refresh(self, value: str) -> str:
        self._refresh_token_str = value
        try:
            from rest_framework_simplejwt.tokens import RefreshToken

            self._token = RefreshToken(value)
        except Exception as exc:  # noqa: BLE001
            raise serializers.ValidationError(_("Invalid or expired refresh token.")) from exc
        return value

    def save(self, **kwargs) -> None:
        """Blacklist the token."""
        self._token.blacklist()
