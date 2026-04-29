"""
Base Django settings for Digital Consumption Ecosystem Platform.
Bangladesh-focused production-ready configuration.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Initialise django-environ
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    DATABASE_URL=(str, "postgres://postgres:postgres@localhost:5432/dce_db"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    SECRET_KEY=(str, "change-me-in-production"),
    USE_S3=(bool, False),
)

# Read .env file if present (never required in production — use real env vars)
environ.Env.read_env(os.path.join(BASE_DIR, ".env"), overwrite=False)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY: str = env("SECRET_KEY")

ALLOWED_HOSTS: list[str] = env("ALLOWED_HOSTS")

AUTH_USER_MODEL = "accounts.User"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

ROOT_URLCONF = "config.urls"

SITE_ID = 1

# ---------------------------------------------------------------------------
# Installed Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    # django-admin-interface must come before django.contrib.admin
    "admin_interface",
    "colorfield",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "django_extensions",
    "storages",
    "channels",
    "django_celery_beat",
    "django_celery_results",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.wallet",
    "apps.ai_gateway",
    "apps.streaming",
    "apps.marketplace",
    "apps.subscriptions",
    "apps.admin_panel",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    # Custom DCE middleware
    "middleware.request_logging.RequestLoggingMiddleware",
    "middleware.device_tracking.DeviceTrackingMiddleware",
    "middleware.rate_limiting.RateLimitingMiddleware",
]

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database — PostgreSQL
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db("DATABASE_URL"),
}

DATABASES["default"]["CONN_MAX_AGE"] = 60  # persistent connections
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 10,
}

# ---------------------------------------------------------------------------
# Cache — Redis
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
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},
        },
        "KEY_PREFIX": "dce",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# ---------------------------------------------------------------------------
# Channels — Django Channels / WebSocket
# ---------------------------------------------------------------------------

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL: str = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"  # stored via django-celery-results
CELERY_CACHE_BACKEND = "django-cache"

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Dhaka"
CELERY_ENABLE_UTC = True

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_WORKER_PREFETCH_MULTIPLIER = 4

CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_TASK_ROUTES = {
    "apps.notifications.tasks.*": {"queue": "notifications"},
    "apps.wallet.tasks.*": {"queue": "payments"},
    "apps.ai_gateway.tasks.*": {"queue": "ai"},
    "apps.streaming.tasks.*": {"queue": "streaming"},
}

CELERY_TASK_DEFAULT_QUEUE = "default"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
        "otp_send": "5/minute",
        "otp_verify": "10/minute",
        "login": "10/minute",
    },
    "EXCEPTION_HANDLER": "apps.accounts.exceptions.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "NON_FIELD_ERRORS_KEY": "errors",
}

# ---------------------------------------------------------------------------
# drf-spectacular — OpenAPI schema & docs
# ---------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    "TITLE": "DCE Platform API",
    "DESCRIPTION": (
        "Bangladesh Digital Consumption Ecosystem — unified API for AI, "
        "streaming, marketplace, subscriptions, and BDT wallet."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "CONTACT": {"name": "DCE Team", "email": "api@dce.com.bd"},
    "LICENSE": {"name": "Proprietary"},
    "SERVERS": [
        {"url": "https://api.dce.com.bd", "description": "Production"},
        {"url": "http://localhost:8000", "description": "Local Dev"},
    ],
    "TAGS": [
        {"name": "auth", "description": "OTP authentication & JWT tokens"},
        {"name": "wallet", "description": "BDT wallet, deposits & withdrawals"},
        {"name": "ai", "description": "AI Gateway — multi-provider chat & services"},
        {"name": "streaming", "description": "Video & course streaming platform"},
        {"name": "marketplace", "description": "Digital product marketplace"},
        {"name": "subscriptions", "description": "Subscription plans & billing"},
        {"name": "notifications", "description": "In-app, SMS & push notifications"},
        {"name": "admin-panel", "description": "Admin management APIs"},
    ],
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
}

# ---------------------------------------------------------------------------
# Simple JWT
# ---------------------------------------------------------------------------

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS: list[str] = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
    ],
)

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-device-id",
    "x-app-version",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# ---------------------------------------------------------------------------
# Authentication password validators
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# Internationalisation — Bangladesh
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & Media files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# File Storage — S3 or local fallback
# ---------------------------------------------------------------------------

USE_S3: bool = env("USE_S3")

if USE_S3:
    AWS_ACCESS_KEY_ID: str = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME: str = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME: str = env("AWS_S3_REGION_NAME", default="ap-southeast-1")
    AWS_S3_CUSTOM_DOMAIN: str = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }
    AWS_DEFAULT_ACL = None  # use bucket policy
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False

    # Media files (user uploads)
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"

    # Static files (collected)
    STATICFILES_STORAGE = "storages.backends.s3boto3.S3StaticStorage"
    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"

# ---------------------------------------------------------------------------
# Email — override in environment-specific settings
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@dce.com.bd")
SERVER_EMAIL = env("SERVER_EMAIL", default="server@dce.com.bd")

# ---------------------------------------------------------------------------
# OTP / SMS settings (Bangladesh)
# ---------------------------------------------------------------------------

OTP_EXPIRY_MINUTES: int = env.int("OTP_EXPIRY_MINUTES", default=5)
OTP_MAX_ATTEMPTS: int = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_LENGTH: int = 6

# Bangladesh SMS Gateway — credentials supplied via env
SMS_GATEWAY_URL: str = env("SMS_GATEWAY_URL", default="https://api.smsgateway.com.bd/api/v3")
SMS_GATEWAY_API_KEY: str = env("SMS_GATEWAY_API_KEY", default="")
SMS_SENDER_ID: str = env("SMS_SENDER_ID", default="DCE_BD")

# ---------------------------------------------------------------------------
# Referral system
# ---------------------------------------------------------------------------

REFERRAL_CODE_LENGTH: int = 8
REFERRAL_BONUS_AMOUNT: int = env.int("REFERRAL_BONUS_AMOUNT", default=50)  # BDT

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{asctime}] {levelname} {message}",
            "style": "{",
        },
        "json": {
            "()": "logging.Formatter",
            "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file_general": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "general.log",
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 10,
            "formatter": "verbose",
        },
        "file_errors": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "errors.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
            "level": "ERROR",
        },
        "file_security": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "security.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
    },
    "root": {
        "handlers": ["console", "file_general"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file_general", "file_errors"],
            "level": "INFO",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "file_security"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file_errors", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
        "celery": {
            "handlers": ["console", "file_general"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "file_general", "file_errors"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Security (base defaults — hardened further in production.py)
# ---------------------------------------------------------------------------

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# ---------------------------------------------------------------------------
# Admin Interface (django-admin-interface)
# ---------------------------------------------------------------------------

X_FRAME_OPTIONS = "SAMEORIGIN"  # admin uses iframes

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

STRIPE_PUBLISHABLE_KEY: str = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY: str = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET: str = env("STRIPE_WEBHOOK_SECRET", default="")

# ---------------------------------------------------------------------------
# Application-level constants
# ---------------------------------------------------------------------------

BANGLADESH_PHONE_REGEX = r"^\+880[1-9]\d{9}$"  # +880 followed by 10 digits

SUPPORTED_CONTENT_TYPES = [
    "video",
    "audio",
    "ebook",
    "course",
    "software",
    "game",
]
