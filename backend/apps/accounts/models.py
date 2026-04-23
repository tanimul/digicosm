"""
Account models for the Digital Consumption Ecosystem Platform.

Models
------
User            — Custom user model (phone-primary, Bangladesh format)
OTPVerification — Time-limited OTP codes for various purposes
UserDevice      — Registered devices for push notifications & session tracking
"""

import hashlib
import secrets
import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.managers import UserManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BANGLADESH_PHONE_REGEX = r"^\+880[1-9]\d{8}$"

phone_validator = RegexValidator(
    regex=BANGLADESH_PHONE_REGEX,
    message=_(
        "Phone number must be in Bangladesh format: +880XXXXXXXXXX "
        "(e.g. +8801712345678)"
    ),
)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(AbstractBaseUser, PermissionsMixin):
    """
    Primary user model.

    Authentication identifier: phone_number (Bangladesh format +880…).
    Email is optional and used for receipts / account recovery.
    """

    class KYCStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUBMITTED = "submitted", _("Submitted")
        VERIFIED = "verified", _("Verified")
        REJECTED = "rejected", _("Rejected")

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    phone_number = models.CharField(
        _("phone number"),
        max_length=15,
        unique=True,
        validators=[phone_validator],
        db_index=True,
        help_text=_("Bangladesh mobile number in E.164 format, e.g. +8801712345678"),
    )

    email = models.EmailField(
        _("email address"),
        blank=True,
        null=True,
        unique=True,
        db_index=True,
        help_text=_("Optional — used for receipts and account recovery"),
    )

    full_name = models.CharField(_("full name"), max_length=150, blank=True)

    avatar = models.ImageField(
        _("avatar"),
        upload_to="avatars/%Y/%m/",
        blank=True,
        null=True,
        help_text=_("Profile picture (JPEG/PNG, max 5 MB)"),
    )

    # ------------------------------------------------------------------
    # Verification flags
    # ------------------------------------------------------------------

    is_verified = models.BooleanField(
        _("phone verified"),
        default=False,
        help_text=_("Becomes True after a successful OTP verification"),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Unset to soft-disable the account without deleting it"),
    )

    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Allows access to Django admin site"),
    )

    # ------------------------------------------------------------------
    # KYC
    # ------------------------------------------------------------------

    kyc_status = models.CharField(
        _("KYC status"),
        max_length=20,
        choices=KYCStatus.choices,
        default=KYCStatus.PENDING,
        db_index=True,
    )

    kyc_submitted_at = models.DateTimeField(
        _("KYC submitted at"), null=True, blank=True
    )

    kyc_reviewed_at = models.DateTimeField(
        _("KYC reviewed at"), null=True, blank=True
    )

    kyc_rejection_reason = models.TextField(
        _("KYC rejection reason"), blank=True
    )

    # ------------------------------------------------------------------
    # Referral system
    # ------------------------------------------------------------------

    referral_code = models.CharField(
        _("referral code"),
        max_length=16,
        unique=True,
        blank=True,
        db_index=True,
        help_text=_("Unique code this user can share to earn bonuses"),
    )

    referred_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referrals",
        verbose_name=_("referred by"),
    )

    referral_bonus_credited = models.BooleanField(
        _("referral bonus credited"),
        default=False,
        help_text=_("True once the sign-up referral bonus has been paid out"),
    )

    # ------------------------------------------------------------------
    # Device / session metadata
    # ------------------------------------------------------------------

    device_tokens = models.JSONField(
        _("device tokens"),
        default=list,
        blank=True,
        help_text=_("FCM / APNs push notification tokens; list of dicts"),
    )

    last_login_ip = models.GenericIPAddressField(
        _("last login IP"),
        null=True,
        blank=True,
        protocol="both",
        unpack_ipv4=True,
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    # ------------------------------------------------------------------
    # Django auth configuration
    # ------------------------------------------------------------------

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["full_name"]

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["-date_joined"]
        indexes = [
            models.Index(fields=["phone_number"], name="idx_user_phone"),
            models.Index(fields=["referral_code"], name="idx_user_referral"),
            models.Index(fields=["kyc_status"], name="idx_user_kyc"),
        ]

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.phone_number} ({self.full_name or 'unnamed'})"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def short_name(self) -> str:
        """Return the first word of full_name."""
        return self.full_name.split()[0] if self.full_name else self.phone_number

    @property
    def is_kyc_verified(self) -> bool:
        return self.kyc_status == self.KYCStatus.VERIFIED

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        # Auto-generate referral code on first save
        if not self.referral_code:
            from apps.accounts.utils import generate_referral_code

            self.referral_code = generate_referral_code()
        super().save(*args, **kwargs)

    def get_full_name(self) -> str:
        return self.full_name.strip() if self.full_name else ""

    def get_short_name(self) -> str:
        return self.short_name

    def update_last_login_ip(self, ip: str) -> None:
        """Persist the caller's IP without triggering a full model save."""
        User.objects.filter(pk=self.pk).update(last_login_ip=ip)
        self.last_login_ip = ip

    def add_device_token(self, token: str, platform: str = "fcm") -> None:
        """Append a push token (de-duplicated by value)."""
        tokens: list[dict] = list(self.device_tokens)
        if not any(t.get("token") == token for t in tokens):
            tokens.append({"token": token, "platform": platform})
            self.device_tokens = tokens
            User.objects.filter(pk=self.pk).update(device_tokens=tokens)

    def remove_device_token(self, token: str) -> None:
        """Remove a specific push token."""
        tokens = [t for t in self.device_tokens if t.get("token") != token]
        self.device_tokens = tokens
        User.objects.filter(pk=self.pk).update(device_tokens=tokens)


# ---------------------------------------------------------------------------
# OTP Verification
# ---------------------------------------------------------------------------


class OTPVerification(models.Model):
    """
    One-time password record.

    The raw OTP code is **never** stored — only a SHA-256 hash.
    Consumers should call `verify(raw_code)` to check validity.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", _("Login")
        REGISTER = "register", _("Register")
        WITHDRAWAL = "withdrawal", _("Withdrawal")
        PASSWORD_RESET = "password_reset", _("Password Reset")
        PHONE_CHANGE = "phone_change", _("Phone Change")
        KYC = "kyc", _("KYC Verification")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="otp_verifications",
        verbose_name=_("user"),
    )

    otp_hash = models.CharField(
        _("OTP hash"),
        max_length=64,
        help_text=_("SHA-256 hex digest of the 6-digit OTP code"),
    )

    purpose = models.CharField(
        _("purpose"),
        max_length=20,
        choices=Purpose.choices,
        db_index=True,
    )

    expires_at = models.DateTimeField(_("expires at"), db_index=True)

    is_used = models.BooleanField(_("is used"), default=False, db_index=True)

    attempts = models.PositiveSmallIntegerField(
        _("verification attempts"),
        default=0,
        help_text=_("Number of failed verification attempts"),
    )

    ip_address = models.GenericIPAddressField(
        _("requester IP"),
        null=True,
        blank=True,
        protocol="both",
        unpack_ipv4=True,
    )

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("OTP verification")
        verbose_name_plural = _("OTP verifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "is_used"], name="idx_otp_user_purpose"),
            models.Index(fields=["expires_at"], name="idx_otp_expires"),
        ]

    def __str__(self) -> str:
        return f"OTP({self.purpose}) for {self.user.phone_number} — {'used' if self.is_used else 'pending'}"

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def _hash_otp(cls, raw_code: str) -> str:
        """Return the SHA-256 hex digest of raw_code."""
        return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()

    @classmethod
    def create_otp(
        cls,
        user: User,
        purpose: str,
        raw_code: str,
        expires_at,
        ip_address: str | None = None,
    ) -> "OTPVerification":
        """
        Create and persist a new OTP record.

        Invalidates all previous unused OTPs for the same user+purpose
        before creating the new one.
        """
        # Invalidate previous OTPs for same user + purpose
        cls.objects.filter(
            user=user,
            purpose=purpose,
            is_used=False,
        ).update(is_used=True)

        return cls.objects.create(
            user=user,
            otp_hash=cls._hash_otp(raw_code),
            purpose=purpose,
            expires_at=expires_at,
            ip_address=ip_address,
        )

    # ------------------------------------------------------------------
    # Instance methods
    # ------------------------------------------------------------------

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """An OTP is valid if it is unused, unexpired, and not exhausted."""
        from django.conf import settings

        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        return not self.is_used and not self.is_expired and self.attempts < max_attempts

    def verify(self, raw_code: str) -> bool:
        """
        Verify a raw OTP code against the stored hash.

        Increments the attempt counter on failure.
        Marks the OTP as used on success.
        Returns True on success, False on failure.
        """
        if not self.is_valid:
            return False

        if self._hash_otp(raw_code) == self.otp_hash:
            self.is_used = True
            self.save(update_fields=["is_used"])
            return True

        self.attempts += 1
        self.save(update_fields=["attempts"])
        return False


# ---------------------------------------------------------------------------
# User Device
# ---------------------------------------------------------------------------


class UserDevice(models.Model):
    """
    Tracks physical devices associated with a user.

    Used for push notifications, session management, and fraud detection.
    """

    class DeviceType(models.TextChoices):
        MOBILE_ANDROID = "android", _("Android Mobile")
        MOBILE_IOS = "ios", _("iOS Mobile")
        WEB = "web", _("Web Browser")
        TABLET = "tablet", _("Tablet")
        DESKTOP = "desktop", _("Desktop")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name=_("user"),
    )

    device_id = models.CharField(
        _("device ID"),
        max_length=255,
        db_index=True,
        help_text=_("Unique hardware or browser fingerprint identifier"),
    )

    device_type = models.CharField(
        _("device type"),
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.MOBILE_ANDROID,
    )

    device_name = models.CharField(
        _("device name"),
        max_length=100,
        blank=True,
        help_text=_('Human-readable label, e.g. "Bashir\'s Galaxy S23"'),
    )

    push_token = models.TextField(
        _("push token"),
        blank=True,
        help_text=_("FCM registration token or APNs device token"),
    )

    app_version = models.CharField(
        _("app version"),
        max_length=20,
        blank=True,
        help_text=_('Semantic version of the client app, e.g. "2.3.1"'),
    )

    os_version = models.CharField(
        _("OS version"),
        max_length=40,
        blank=True,
    )

    last_active = models.DateTimeField(
        _("last active"),
        default=timezone.now,
        db_index=True,
    )

    last_ip = models.GenericIPAddressField(
        _("last IP"),
        null=True,
        blank=True,
        protocol="both",
        unpack_ipv4=True,
    )

    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Inactive devices will not receive push notifications"),
    )

    is_trusted = models.BooleanField(
        _("is trusted"),
        default=False,
        help_text=_("Trusted devices may bypass additional auth checks"),
    )

    created_at = models.DateTimeField(_("registered at"), auto_now_add=True)

    class Meta:
        verbose_name = _("user device")
        verbose_name_plural = _("user devices")
        unique_together = [("user", "device_id")]
        ordering = ["-last_active"]
        indexes = [
            models.Index(fields=["user", "is_active"], name="idx_device_user_active"),
            models.Index(fields=["push_token"], name="idx_device_push_token"),
        ]

    def __str__(self) -> str:
        return f"{self.get_device_type_display()} — {self.user.phone_number} ({self.device_id[:12]}…)"

    def touch(self, ip: str | None = None) -> None:
        """Update last_active timestamp and optionally the IP address."""
        update_fields = ["last_active"]
        self.last_active = timezone.now()
        if ip:
            self.last_ip = ip
            update_fields.append("last_ip")
        self.save(update_fields=update_fields)
