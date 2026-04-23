"""
Development settings for Digital Consumption Ecosystem Platform.

Extends base settings with developer-friendly defaults:
  - DEBUG = True
  - Local PostgreSQL database
  - Console email backend
  - Relaxed CORS
  - Django Debug Toolbar (optional)
  - Verbose logging to console
"""

from .base import *  # noqa: F401, F403
from .base import INSTALLED_APPS, LOGGING, MIDDLEWARE, env

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = True

SECRET_KEY = env(
    "SECRET_KEY",
    default="dev-insecure-secret-key-do-not-use-in-production-ever",
)

ALLOWED_HOSTS = ["*"]

# ---------------------------------------------------------------------------
# Database — local PostgreSQL
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", default="dce_dev"),
        "USER": env("DB_USER", default="postgres"),
        "PASSWORD": env("DB_PASSWORD", default="postgres"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
        "CONN_MAX_AGE": 0,  # new connection each request in dev
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# ---------------------------------------------------------------------------
# Cache — local Redis (fall back to LocMemCache if Redis not running)
# ---------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,  # don't crash dev server if Redis is down
        },
        "KEY_PREFIX": "dce_dev",
    }
}

# ---------------------------------------------------------------------------
# Email — console output
# ---------------------------------------------------------------------------

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------------
# CORS — allow everything in dev
# ---------------------------------------------------------------------------

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Static / Media
# ---------------------------------------------------------------------------

# Use local file system, never S3, in development
USE_S3 = False
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# ---------------------------------------------------------------------------
# Django Debug Toolbar (install separately: pip install django-debug-toolbar)
# ---------------------------------------------------------------------------

try:
    import debug_toolbar  # noqa: F401

    INSTALLED_APPS = INSTALLED_APPS + ["debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE
    INTERNAL_IPS = ["127.0.0.1", "::1"]
    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG,
        "DISABLE_PANELS": ["debug_toolbar.panels.redirects.RedirectsPanel"],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Logging — verbose console output in development
# ---------------------------------------------------------------------------

LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # type: ignore[index]
LOGGING["loggers"]["django"]["level"] = "DEBUG"  # type: ignore[index]

# Add a more readable console formatter for dev
LOGGING["formatters"]["dev"] = {  # type: ignore[index]
    "format": "\033[32m[{asctime}]\033[0m \033[1m{levelname:<8}\033[0m {name} — {message}",
    "style": "{",
}
LOGGING["handlers"]["console"]["formatter"] = "dev"  # type: ignore[index]

# ---------------------------------------------------------------------------
# Celery — eager execution for easier debugging
# ---------------------------------------------------------------------------

CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/1")

# ---------------------------------------------------------------------------
# Security — relaxed for local development
# ---------------------------------------------------------------------------

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# ---------------------------------------------------------------------------
# SMS OTP — skip actual sending in dev; log the OTP instead
# ---------------------------------------------------------------------------

SMS_BACKEND = "stub"  # "stub" | "live"

# ---------------------------------------------------------------------------
# Django Extensions shell_plus
# ---------------------------------------------------------------------------

SHELL_PLUS = "ipython"
SHELL_PLUS_PRINT_SQL = True
