"""
URL patterns for the accounts application.

All routes are mounted by config/urls.py under /api/v1/auth/.

Full paths after the /api/v1/auth/ prefix:
  POST   register/              Create a new user account
  POST   otp/send/              Request an OTP via SMS
  POST   otp/verify/            Submit OTP code for verification
  POST   login/                 Authenticate and receive JWT tokens
  POST   logout/                Blacklist the refresh token
  GET    profile/               Retrieve authenticated user's profile
  PATCH  profile/               Partially update the user's profile
  POST   password/change/       Change password (requires current password)
  POST   token/refresh/         Refresh the access token
"""

from django.urls import path

from apps.accounts.views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    RefreshTokenView,
    RegisterView,
    SendOTPView,
    UserProfileView,
    VerifyOTPView,
)

app_name = "accounts"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Registration & OTP verification                                     #
    # ------------------------------------------------------------------ #
    path(
        "register/",
        RegisterView.as_view(),
        name="register",
    ),
    path(
        "otp/send/",
        SendOTPView.as_view(),
        name="otp-send",
    ),
    path(
        "otp/verify/",
        VerifyOTPView.as_view(),
        name="otp-verify",
    ),
    # ------------------------------------------------------------------ #
    # Authentication                                                      #
    # ------------------------------------------------------------------ #
    path(
        "login/",
        LoginView.as_view(),
        name="login",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
    path(
        "token/refresh/",
        RefreshTokenView.as_view(),
        name="token-refresh",
    ),
    # ------------------------------------------------------------------ #
    # Profile management                                                  #
    # ------------------------------------------------------------------ #
    path(
        "profile/",
        UserProfileView.as_view(),
        name="profile",
    ),
    # ------------------------------------------------------------------ #
    # Password management                                                 #
    # ------------------------------------------------------------------ #
    path(
        "password/change/",
        ChangePasswordView.as_view(),
        name="password-change",
    ),
]
