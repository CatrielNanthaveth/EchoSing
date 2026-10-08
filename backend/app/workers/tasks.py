"""Celery tasks."""

import asyncio
import logging
import uuid

from app.core.config import get_settings
from app.services.pipeline.runner import run_job
from app.workers.celery_app import INGESTION_TASK, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name=INGESTION_TASK)
def run_ingestion(job_id: str) -> None:
    """Run the ingestion pipeline for a job.

    Outcomes (done, failed, skipped) are recorded in ``ingestion_jobs``; stage
    failures are not raised, so Celery does not retry deterministic errors.

    Args:
        job_id: Id of the ``IngestionJob`` to process.
    """
    outcome = asyncio.run(run_job(uuid.UUID(job_id), get_settings()))
    if outcome.skipped:
        logger.info(
            "Ingestion job %s skipped (already %s)", job_id, outcome.stage.value
        )
    elif outcome.error:
        logger.error("Ingestion job %s failed: %s", job_id, outcome.error)
    else:
        logger.info("Ingestion job %s done (song %s)", job_id, outcome.song_id)
