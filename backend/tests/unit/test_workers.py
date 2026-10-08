import logging
import uuid
from types import SimpleNamespace
from unittest.mock import ANY, create_autospec

import pytest
from celery import Celery

from app.core.config import Settings
from app.domain.enums import IngestionStage
from app.services.pipeline.runner import PipelineOutcome
from app.workers import tasks
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


def test_celery_app_has_a_time_limit() -> None:
    assert create_celery_app("redis://example:6379/0").conf.task_time_limit == 3600


@pytest.mark.parametrize(
    ("outcome_fields", "level", "text"),
    [
        ({"stage": IngestionStage.DONE}, logging.INFO, "done"),
        (
            {"stage": IngestionStage.FAILED, "error": "transcribing: boom"},
            logging.ERROR,
            "failed: transcribing: boom",
        ),
        ({"stage": IngestionStage.DONE, "skipped": True}, logging.INFO, "skipped"),
    ],
)
def test_task_runs_the_job_and_logs_its_outcome(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    outcome_fields: dict[str, object],
    level: int,
    text: str,
) -> None:
    job_id = uuid.uuid4()
    received: list[uuid.UUID] = []

    async def fake_run_job(job: uuid.UUID, settings: Settings) -> PipelineOutcome:
        received.append(job)
        return PipelineOutcome.model_validate(
            {"job_id": job, "song_id": uuid.uuid4(), **outcome_fields}
        )

    monkeypatch.setattr(tasks, "run_job", fake_run_job)

    with caplog.at_level(logging.INFO, logger="app.workers.tasks"):
        run_ingestion(str(job_id))

    assert received == [job_id]
    assert any(r.levelno == level and text in r.getMessage() for r in caplog.records)


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
