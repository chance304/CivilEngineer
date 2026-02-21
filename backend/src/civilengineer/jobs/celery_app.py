"""
Celery application.

Broker + result backend: Redis (already required for refresh tokens).
"""

from __future__ import annotations

from celery import Celery

from civilengineer.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "civilengineer",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
        include=["civilengineer.jobs.plot_job", "civilengineer.jobs.design_job"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        broker_connection_retry_on_startup=True,
        # Limit memory per task to prevent runaway workers
        worker_max_tasks_per_child=50,
    )
    return app


celery_app = create_celery_app()
