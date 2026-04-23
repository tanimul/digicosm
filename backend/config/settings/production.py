"""
Production settings for Digital Consumption Ecosystem Platform.

Extends base settings with hardened security, Sentry error tracking,
full S3 storage, proper email backend, and performance optimisations
appropriate for a Bangladesh-facing production deployment.
"""

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from .base import *  # noqa: F401, F403
from .base import LOGGING, env

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = False

SECRET_KEY: str = env("SECRET_KEY")  # must be set in environment; no default

ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS")

# ---------------------------------------------------------------------------
# Database — managed PostgreSQL (RDS / Cloud SQL / managed Postgres)
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
            "sslmode": env("DB_SSLMODE", default="require"),
        },
    }
}

# ---------------------------------------------------------------------------
# Cache — Redis (ElastiCache or managed Redis)
# ---------------------------------------------------------------------------

REDIS_URL: str = env("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "RETRY_ON_TIMEOUT": True,
            "CONNECTION_POOL_KWARGS": {"max_connections": 100},
            "PASSWORD": env("REDIS_PASSWORD", default=""),
        },
        "KEY_PREFIX": "dce_prod",
        "TIMEOUT": 300,
    }
}

# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

# HTTPS redirect
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS — tell browsers to always use HTTPS (1 year)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie security
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 86400  # 1 day

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Content security
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# Referrer policy
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ---------------------------------------------------------------------------
# Email — SendGrid / SMTP (Bangladesh ISP-friendly)
# ---------------------------------------------------------------------------

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="apikey")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@dce.com.bd")
SERVER_EMAIL = env("SERVER_EMAIL", default="server@dce.com.bd")
ADMINS = [
    (name, email)
    for pair in env.list("DJANGO_ADMINS", default=[])
    for name, email in [pair.split(":")]
]

# ---------------------------------------------------------------------------
# File Storage — AWS S3
# ---------------------------------------------------------------------------

USE_S3 = True

AWS_ACCESS_KEY_ID: str = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: str = env("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME: str = env("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME: str = env("AWS_S3_REGION_NAME", default="ap-southeast-1")
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = False
AWS_S3_SIGNATURE_VERSION = "s3v4"

DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
STATICFILES_STORAGE = "storages.backends.s3boto3.S3StaticStorage"
MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"

# ---------------------------------------------------------------------------
# CORS — restrict to known origins
# ---------------------------------------------------------------------------

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Celery — production broker
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_USE_SSL = env.bool("CELERY_BROKER_USE_SSL", default=False)
CELERY_TASK_ALWAYS_EAGER = False

# ---------------------------------------------------------------------------
# Sentry — error tracking & performance monitoring
# ---------------------------------------------------------------------------

SENTRY_DSN: str = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT: str = env("SENTRY_ENVIRONMENT", default="production")
SENTRY_TRACES_SAMPLE_RATE: float = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1)

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
                signals_spans=True,
            ),
            CeleryIntegration(monitor_beat_tasks=True),
            RedisIntegration(),
        ],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,  # GDPR / privacy compliance
        environment=SENTRY_ENVIRONMENT,
        release=env("APP_VERSION", default="unknown"),
        before_send=_before_send_sentry,
    )


def _before_send_sentry(event: dict, hint: dict) -> dict | None:
    """Strip sensitive data before sending to Sentry."""
    # Redact Authorization headers
    request = event.get("request", {})
    headers = request.get("headers", {})
    if "Authorization" in headers:
        headers["Authorization"] = "[Filtered]"
    if "Cookie" in headers:
        headers["Cookie"] = "[Filtered]"

    # Do not send 404s or permission errors to Sentry
    if "exc_info" in hint:
        import django.http
        exc_type = hint["exc_info"][0]
        ignored = (
            django.http.Http404,
            django.core.exceptions.PermissionDenied,  # type: ignore[attr-defined]
        )
        if issubclass(exc_type, ignored):
            return None

    return event


# ---------------------------------------------------------------------------
# Logging — structured JSON to stdout (captured by log aggregators)
# ---------------------------------------------------------------------------

LOGGING["handlers"]["console"]["formatter"] = "json"  # type: ignore[index]

# Reduce noise in production
LOGGING["loggers"]["django"]["level"] = "WARNING"  # type: ignore[index]
LOGGING["loggers"]["apps"]["level"] = "INFO"  # type: ignore[index]

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

# Cache database queries for frequently accessed data
CONN_MAX_AGE = 60

# WhiteNoise compression already set in base; ensure it is active
WHITENOISE_AUTOREFRESH = False
WHITENOISE_MAX_AGE = 31536000  # 1 year for versioned assets

# ---------------------------------------------------------------------------
# Rate-limiting adjustments for production traffic
# ---------------------------------------------------------------------------

# Tighten OTP rate limits in production
REST_FRAMEWORK_THROTTLE_RATES_OVERRIDE = {  # applied programmatically
    "otp_send": "3/minute",
    "login": "5/minute",
}
