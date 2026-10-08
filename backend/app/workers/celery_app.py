"""Celery application running the ingestion pipeline.

Start a worker (from ``backend/``)::

    uv run celery -A app.workers.celery_app worker --pool=solo --loglevel=info

``--pool=solo`` runs one task at a time in the main process: it is required on
Windows and keeps GPU jobs from competing for the 8 GB of VRAM.
"""

from celery import Celery

from app.core.config import get_settings

INGESTION_TASK = "ingestion.run"


def create_celery_app(broker_url: str) -> Celery:
    """Create the Celery application.

    Job state lives in PostgreSQL (``ingestion_jobs``), so no result backend is
    configured.

    Args:
        broker_url: Redis URL used as message broker.

    Returns:
        The configured Celery application.
    """
    app = Celery("echosing", broker=broker_url, include=["app.workers.tasks"])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        # Ingestion jobs are long: acknowledge after completion so a crashed
        # worker does not lose the job, and fetch one job at a time.
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # Safety net: a whole song takes a few minutes on a GPU.
        task_time_limit=3600,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = create_celery_app(get_settings().redis_url)
