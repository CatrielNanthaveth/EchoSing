import logging
import uuid
from types import SimpleNamespace
from unittest.mock import ANY, create_autospec

import pytest
from celery import Celery

from app.workers.celery_app import INGESTION_TASK, celery_app, create_celery_app
from app.workers.queue import CeleryJobQueue, QueueUnavailableError
from app.workers.tasks import run_ingestion


def test_ingestion_task_is_registered() -> None:
    assert INGESTION_TASK in celery_app.tasks


def test_celery_app_is_configured_for_long_gpu_jobs() -> None:
    app = create_celery_app("redis://example:6379/0")

    assert app.conf.broker_url == "redis://example:6379/0"
    assert app.conf.task_acks_late is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_ignore_result is True


def test_placeholder_task_logs_the_job(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.workers.tasks"):
        run_ingestion("job-123")

    assert "job-123" in caplog.text


async def test_celery_queue_publishes_ingestion_task() -> None:
    app = create_autospec(Celery, instance=True)
    app.send_task.return_value = SimpleNamespace(id="celery-task-id")
    job_id = uuid.uuid4()

    task_id = await CeleryJobQueue(app).enqueue_ingestion(job_id)

    assert task_id == "celery-task-id"
    app.send_task.assert_called_once_with(
        INGESTION_TASK, args=[str(job_id)], retry_policy=ANY
    )


async def test_celery_queue_wraps_broker_errors() -> None:
    app = create_autospec(Celery, instance=True)
    app.send_task.side_effect = ConnectionError("redis down")

    with pytest.raises(QueueUnavailableError):
        await CeleryJobQueue(app).enqueue_ingestion(uuid.uuid4())
