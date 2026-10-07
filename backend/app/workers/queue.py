"""Job queue abstraction used by the API to schedule background work."""

import uuid
from functools import partial
from typing import Protocol

import anyio.to_thread
from celery import Celery

from app.workers.celery_app import INGESTION_TASK, celery_app

# Fail fast when the broker is down instead of blocking the request for long.
_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.5,
    "interval_max": 1,
}


class QueueUnavailableError(Exception):
    """The job could not be handed to the queue (e.g. the broker is down)."""


class JobQueue(Protocol):
    """Schedules background jobs."""

    async def enqueue_ingestion(self, job_id: uuid.UUID) -> str:
        """Schedule the ingestion pipeline for a job.

        Args:
            job_id: Id of the ``IngestionJob`` to process.

        Returns:
            Id of the queued task.

        Raises:
            QueueUnavailableError: If the job could not be queued.
        """
        ...


class CeleryJobQueue:
    """``JobQueue`` backed by Celery."""

    def __init__(self, app: Celery) -> None:
        """Initialize the queue.

        Args:
            app: Celery application used to publish tasks.
        """
        self._app = app

    async def enqueue_ingestion(self, job_id: uuid.UUID) -> str:
        """Publish an ingestion task. See ``JobQueue``."""
        # send_task performs blocking network I/O, so it runs in a thread.
        publish = partial(
            self._app.send_task,
            INGESTION_TASK,
            args=[str(job_id)],
            retry_policy=_PUBLISH_RETRY_POLICY,
        )
        try:
            result = await anyio.to_thread.run_sync(publish)
        except Exception as error:
            raise QueueUnavailableError(f"Could not queue job {job_id}") from error
        return str(result.id)


def get_job_queue() -> JobQueue:
    """Provide the application job queue.

    Returns:
        A ``CeleryJobQueue`` using the shared Celery application.
    """
    return CeleryJobQueue(celery_app)
