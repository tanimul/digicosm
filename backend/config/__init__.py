# This makes config a Python package and ensures the Celery app is always
# imported when Django starts, so that shared_task decorators work correctly.
from config.celery import app as celery_app

__all__ = ("celery_app",)
