"""
API views for the accounts application.

Endpoints
---------
POST   /api/v1/auth/register/          RegisterView
POST   /api/v1/auth/otp/send/          SendOTPView
POST   /api/v1/auth/otp/verify/        VerifyOTPView
POST   /api/v1/auth/login/             LoginView
POST   /api/v1/auth/logout/            LogoutView
GET    /api/v1/auth/profile/           UserProfileView
PATCH  /api/v1/auth/profile/           UserProfileView
POST   /api/v1/auth/password/change/   ChangePasswordView
POST   /api/v1/auth/token/refresh/     RefreshTokenView
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.models import OTPVerification, User, UserDevice
from apps.accounts.serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    OTPVerificationSerializer,
    SendOTPSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    UserRegistrationSerializer,
)
from apps.accounts.utils import (
    check_otp_rate_limit,
    generate_otp,
    get_client_ip,
    mask_phone_number,
    send_otp_sms,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom throttle classes
# ---------------------------------------------------------------------------


class OTPSendThrottle(AnonRateThrottle):
    scope = "otp_send"


class OTPVerifyThrottle(AnonRateThrottle):
    scope = "otp_verify"


class LoginThrottle(AnonRateThrottle):
    scope = "login"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _success(data: dict | None = None, message: str = "Success", status_code: int = 200) -> Response:
    """Standardised success response envelope."""
    payload: dict = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return Response(payload, status=status_code)


def _error(message: str, errors: dict | None = None, status_code: int = 400) -> Response:
    """Standardised error response envelope."""
    payload: dict = {"success": False, "message": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=status_code)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@method_decorator(never_cache, name="dispatch")
class RegisterView(APIView):
    """
    POST /api/v1/auth/register/

    Create a new unverified user account.
    The caller must subsequently request and verify an OTP to activate it.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    parser_classes = [JSONParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = UserRegistrationSerializer(
            data=request.data,
            context={"request": request},
        )
        if not serializer.is_valid():
            return _error("Registration failed.", errors=serializer.errors, status_code=400)

        user: User = serializer.save()

        # Automatically dispatch a registration OTP
        self._dispatch_registration_otp(user, get_client_ip(request))

        logger.info(
            "User registered: id=%s phone=%s",
            user.pk,
            mask_phone_number(user.phone_number),
        )

        return _success(
            data={
                "user_id": str(user.pk),
                "phone_number": mask_phone_number(user.phone_number),
                "message": "Account created. Please verify your phone number with the OTP sent via SMS.",
            },
            message="Registration successful.",
            status_code=201,
        )

    @staticmethod
    def _dispatch_registration_otp(user: User, ip: str | None) -> None:
        """Create an OTP record and fire the SMS in the background."""
        otp_code = generate_otp()
        expiry_minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 5)
        expires_at = timezone.now() + timedelta(minutes=expiry_minutes)

        OTPVerification.create_otp(
            user=user,
            purpose=OTPVerification.Purpose.REGISTER,
            raw_code=otp_code,
            expires_at=expires_at,
            ip_address=ip,
        )

        # Dispatch via Celery task (non-blocking)
        try:
            from apps.accounts.tasks import send_otp_sms_task

            send_otp_sms_task.delay(
                phone_number=user.phone_number,
                otp_code=otp_code,
                purpose=OTPVerification.Purpose.REGISTER,
            )
        except Exception:  # noqa: BLE001
            # Fall back to synchronous send if Celery is unavailable
            send_otp_sms(user.phone_number, otp_code, OTPVerification.Purpose.REGISTER)


# ---------------------------------------------------------------------------
# Send OTP
# ---------------------------------------------------------------------------


@method_decorator(never_cache, name="dispatch")
class SendOTPView(APIView):
    """
    POST /api/v1/auth/otp/send/

    Request a fresh OTP for any supported purpose.
    Rate-limited to prevent SMS bombing.
    """

    permission_classes = [AllowAny]
    throttle_classes = [OTPSendThrottle]
    parser_classes = [JSONParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = SendOTPSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return _error("Invalid request.", errors=serializer.errors)

        phone_number: str = serializer.validated_data["phone_number"]
        purpose: str = serializer.validated_data["purpose"]
        ip: str = get_client_ip(request)

        # Application-level rate limiting (Redis-backed)
        if not check_otp_rate_limit(phone_number, purpose):
            return _error(
                "Too many OTP requests. Please wait before requesting another.",
                status_code=429,
            )

        # Resolve user (may not exist yet for REGISTER purpose)
        user: User | None = serializer.validated_data.get("user")
        if user is None:
            # Registration flow: look up or raise (serializer already validated)
            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return _error("Account not found.", status_code=404)

        otp_code = generate_otp()
        expiry_minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 5)
        expires_at = timezone.now() + timedelta(minutes=expiry_minutes)

        OTPVerification.create_otp(
            user=user,
            purpose=purpose,
            raw_code=otp_code,
            expires_at=expires_at,
            ip_address=ip,
        )

        # Dispatch SMS
        try:
            from apps.accounts.tasks import send_otp_sms_task

            send_otp_sms_task.delay(
                phone_number=phone_number,
                otp_code=otp_code,
                purpose=purpose,
            )
        except Exception:  # noqa: BLE001
            send_otp_sms(phone_number, otp_code, purpose)

        logger.info(
            "OTP dispatched: phone=%s purpose=%s",
            mask_phone_number(phone_number),
            purpose,
        )

        return _success(
            data={
                "phone_number": mask_phone_number(phone_number),
                "expires_in_minutes": expiry_minutes,
            },
            message="OTP sent successfully.",
        )


# ---------------------------------------------------------------------------
# Verify OTP
# ---------------------------------------------------------------------------


@method_decorator(never_cache, name="dispatch")
class VerifyOTPView(APIView):
    """
    POST /api/v1/auth/otp/verify/

    Verify a submitted OTP code.
    On success for REGISTER/LOGIN purposes, also activates the account
    and returns a JWT token pair.
    """

    permission_classes = [AllowAny]
    throttle_classes = [OTPVerifyThrottle]
    parser_classes = [JSONParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = OTPVerificationSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return _error("OTP verification failed.", errors=serializer.errors)

        otp_record: OTPVerification = serializer.validated_data["otp_record"]
        user: User = serializer.validated_data["user"]
        raw_code: str = serializer.validated_data["otp_code"]
        purpose: str = serializer.validated_data["purpose"]

        if not otp_record.verify(raw_code):
            remaining = max(
                0,
                getattr(settings, "OTP_MAX_ATTEMPTS", 5) - otp_record.attempts,
            )
            return _error(
                f"Incorrect OTP. {remaining} attempt(s) remaining.",
                status_code=400,
            )

        response_data: dict = {"purpose": purpose}

        # Mark phone as verified on registration / first login
        if purpose in (OTPVerification.Purpose.REGISTER, OTPVerification.Purpose.LOGIN):
            if not user.is_verified:
                User.objects.filter(pk=user.pk).update(is_verified=True)
                user.is_verified = True

            # Issue JWT tokens
            from rest_framework_simplejwt.tokens import RefreshToken

            refresh = RefreshToken.for_user(user)
            response_data["tokens"] = {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }

        logger.info(
            "OTP verified: user=%s purpose=%s",
            user.pk,
            purpose,
        )

        return _success(data=response_data, message="OTP verified successfully.")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@method_decorator(never_cache, name="dispatch")
class LoginView(APIView):
    """
    POST /api/v1/auth/login/

    Authenticate with phone_number + password and receive JWT tokens.
    Optionally register a device for push notifications.
    """

    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    parser_classes = [JSONParser, FormParser]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            logger.warning(
                "Failed login attempt from IP=%s errors=%s",
                get_client_ip(request),
                serializer.errors,
            )
            return _error("Login failed.", errors=serializer.errors, status_code=401)

        user: User = serializer.validated_data["user"]
        tokens = serializer.get_tokens(user)

        # Persist last login IP
        user.update_last_login_ip(get_client_ip(request))

        # Register device if provided
        device_id: str = serializer.validated_data.get("device_id", "")
        if device_id:
            self._register_device(
                user=user,
                device_id=device_id,
                device_type=serializer.validated_data.get(
                    "device_type", UserDevice.DeviceType.MOBILE_ANDROID
                ),
                push_token=serializer.validated_data.get("push_token", ""),
                ip=get_client_ip(request),
            )

        logger.info("User logged in: id=%s ip=%s", user.pk, get_client_ip(request))

        return _success(
            data={
                "tokens": tokens,
                "user": {
                    "id": str(user.pk),
                    "phone_number": mask_phone_number(user.phone_number),
                    "full_name": user.full_name,
                    "is_verified": user.is_verified,
                    "kyc_status": user.kyc_status,
                },
            },
            message="Login successful.",
        )

    @staticmethod
    def _register_device(
        user: User,
        device_id: str,
        device_type: str,
        push_token: str,
        ip: str,
    ) -> UserDevice:
        device, _ = UserDevice.objects.update_or_create(
            user=user,
            device_id=device_id,
            defaults={
                "device_type": device_type,
                "push_token": push_token,
                "last_active": timezone.now(),
                "last_ip": ip,
                "is_active": True,
            },
        )
        return device


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/

    Blacklist the submitted refresh token, effectively logging the user out.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("Logout failed.", errors=serializer.errors)

        try:
            serializer.save()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Logout token blacklist error: %s", exc)
            return _error("Could not invalidate token.", status_code=400)

        logger.info("User logged out: id=%s", request.user.pk)
        return _success(message="Logged out successfully.")


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------


class UserProfileView(APIView):
    """
    GET   /api/v1/auth/profile/   — Retrieve authenticated user's profile
    PATCH /api/v1/auth/profile/   — Update profile fields (partial update)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request: Request) -> Response:
        serializer = UserProfileSerializer(
            request.user, context={"request": request}
        )
        return _success(data=serializer.data, message="Profile retrieved.")

    def patch(self, request: Request) -> Response:
        serializer = UserProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        if not serializer.is_valid():
            return _error("Profile update failed.", errors=serializer.errors)

        serializer.save()
        return _success(
            data=UserProfileSerializer(
                request.user, context={"request": request}
            ).data,
            message="Profile updated successfully.",
        )


# ---------------------------------------------------------------------------
# Change Password
# ---------------------------------------------------------------------------


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/password/change/

    Change the authenticated user's password.
    Requires current password for verification.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return _error("Password change failed.", errors=serializer.errors)

        serializer.save()
        logger.info("Password changed for user id=%s", request.user.pk)
        return _success(message="Password changed successfully. Please log in again.")


# ---------------------------------------------------------------------------
# Token Refresh — extend simplejwt's view with standard response envelope
# ---------------------------------------------------------------------------


class RefreshTokenView(TokenRefreshView):
    """
    POST /api/v1/auth/token/refresh/

    Returns a new access token given a valid refresh token.
    Wraps simplejwt's default behaviour in the platform's response envelope.
    """

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        return _success(
            data=serializer.validated_data,
            message="Token refreshed successfully.",
        )
