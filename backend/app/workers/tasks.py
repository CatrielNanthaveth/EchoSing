"""Celery tasks."""

import logging

from app.workers.celery_app import INGESTION_TASK, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name=INGESTION_TASK)
def run_ingestion(job_id: str) -> None:
    """Run the ingestion pipeline for a job.

    Placeholder until the pipeline stages are implemented (US-2.2 to US-2.6):
    it only acknowledges the job, which stays in the ``queued`` stage.

    Args:
        job_id: Id of the ``IngestionJob`` to process.
    """
    logger.info("Received ingestion job %s (pipeline not implemented yet)", job_id)
