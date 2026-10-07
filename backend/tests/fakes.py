"""Test doubles shared by unit and integration tests."""

import uuid

from app.workers.queue import QueueUnavailableError


class FakeJobQueue:
    """In-memory ``JobQueue`` that records jobs or simulates a broker outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.fail = fail

    async def enqueue_ingestion(self, job_id: uuid.UUID) -> str:
        if self.fail:
            raise QueueUnavailableError("broker is down")
        self.enqueued.append(job_id)
        return f"task-{job_id}"
