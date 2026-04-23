"""
Celery application configuration for the Digital Consumption Ecosystem Platform.

Usage
-----
Start the default worker:
    celery -A config worker -l info

Start beat scheduler:
    celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

Start Flower monitoring (pip install flower):
    celery -A config flower --port=5555
"""

import os

from celery import Celery
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    worker_ready,
    worker_shutdown,
)
from django.conf import settings

# ---------------------------------------------------------------------------
# Set default Django settings module before anything else
# ---------------------------------------------------------------------------

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# ---------------------------------------------------------------------------
# Create Celery application
# ---------------------------------------------------------------------------

app = Celery("dce")

# ---------------------------------------------------------------------------
# Load config from Django settings (namespace = CELERY_*)
# ---------------------------------------------------------------------------

app.config_from_object("django.conf:settings", namespace="CELERY")

# ---------------------------------------------------------------------------
# Auto-discover tasks in all INSTALLED_APPS
# ---------------------------------------------------------------------------

app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

# ---------------------------------------------------------------------------
# Beat schedule — periodic tasks
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {
    # Clean up expired OTP records every 30 minutes
    "cleanup-expired-otps": {
        "task": "apps.accounts.tasks.cleanup_expired_otps",
        "schedule": 30 * 60,  # seconds
        "options": {"queue": "default"},
    },
    # Sync subscription statuses every hour
    "sync-subscription-statuses": {
        "task": "apps.subscriptions.tasks.sync_subscription_statuses",
        "schedule": 60 * 60,
        "options": {"queue": "payments"},
    },
    # Send daily digest notifications
    "send-daily-digest": {
        "task": "apps.notifications.tasks.send_daily_digest",
        "schedule": {
            "hour": 9,
            "minute": 0,
        },
        "options": {"queue": "notifications"},
    },
    # Refresh AI recommendation cache every 6 hours
    "refresh-ai-recommendations": {
        "task": "apps.ai_gateway.tasks.refresh_recommendation_cache",
        "schedule": 6 * 60 * 60,
        "options": {"queue": "ai"},
    },
    # Clean up stale streaming sessions every 15 minutes
    "cleanup-stale-streams": {
        "task": "apps.streaming.tasks.cleanup_stale_sessions",
        "schedule": 15 * 60,
        "options": {"queue": "streaming"},
    },
    # Reconcile wallet transactions every 5 minutes
    "reconcile-wallet-transactions": {
        "task": "apps.wallet.tasks.reconcile_pending_transactions",
        "schedule": 5 * 60,
        "options": {"queue": "payments"},
    },
}

# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@setup_logging.connect
def config_loggers(*args, **kwargs) -> None:
    """Prevent Celery from overriding Django's logging configuration."""
    pass  # Django logging is already configured in settings


@worker_ready.connect
def on_worker_ready(sender, **kwargs) -> None:
    """Log when a worker comes online."""
    import logging

    logger = logging.getLogger("celery.worker")
    logger.info("Celery worker ready — DCE Platform")


@worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs) -> None:
    """Log when a worker shuts down."""
    import logging

    logger = logging.getLogger("celery.worker")
    logger.info("Celery worker shutting down — DCE Platform")


@task_prerun.connect
def on_task_prerun(task_id: str, task, args, kwargs, **extras) -> None:
    """Log task start for observability."""
    import logging

    logging.getLogger("celery.task").debug(
        "Task starting: %s [%s]", task.name, task_id
    )


@task_postrun.connect
def on_task_postrun(task_id: str, task, args, kwargs, retval, state, **extras) -> None:
    """Log task completion."""
    import logging

    logging.getLogger("celery.task").debug(
        "Task finished: %s [%s] state=%s", task.name, task_id, state
    )


@task_failure.connect
def on_task_failure(
    task_id: str,
    exception: Exception,
    traceback,
    sender,
    **kwargs,
) -> None:
    """Report task failures to Sentry / logging."""
    import logging

    logger = logging.getLogger("celery.task")
    logger.error(
        "Task failed: %s [%s] exception=%s",
        sender.name,
        task_id,
        str(exception),
        exc_info=True,
    )

    # Forward to Sentry if configured
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("celery_task", sender.name)
            scope.set_extra("task_id", task_id)
            sentry_sdk.capture_exception(exception)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Debug task — useful for testing connectivity
# ---------------------------------------------------------------------------


@app.task(bind=True, name="config.celery.debug_task")
def debug_task(self) -> str:
    """Prints the Celery request for debugging purposes."""
    print(f"Request: {self.request!r}")
    return f"OK — worker: {self.request.hostname}"
