"""
Test settings for DCE Platform.
Uses in-memory SQLite and dummy backends for speed.
Override with environment variables when running against real Postgres in CI.
"""

from .base import *  # noqa: F401, F403

# ─── Speed ─────────────────────────────────────────────────────────────────

# SQLite in-memory is fine for unit/integration tests; CI overrides with PG.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Bypass password hashing — dramatically speeds up tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# ─── Cache ─────────────────────────────────────────────────────────────────

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# ─── Channels ──────────────────────────────────────────────────────────────

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# ─── Celery ────────────────────────────────────────────────────────────────

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# ─── Email ─────────────────────────────────────────────────────────────────

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ─── Media ─────────────────────────────────────────────────────────────────

DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"

# ─── Security ──────────────────────────────────────────────────────────────

SECRET_KEY = "test-secret-key-not-for-production"

# Disable middleware that requires Redis/real services in tests
MIDDLEWARE = [m for m in MIDDLEWARE if m not in (  # noqa: F405
    "middleware.rate_limiting.RateLimitingMiddleware",
)]

# ─── Misc ──────────────────────────────────────────────────────────────────

# Disable Sentry in tests
SENTRY_DSN = ""

# Fast OTP for tests
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5

# Fernet key for AI key encryption tests
FERNET_KEY = "dGVzdC1mZXJuZXQta2V5LXdoaWNoLWlzLTMyLWJ5dGVzLWxvbmc="

DEBUG = True
ALLOWED_HOSTS = ["*"]
