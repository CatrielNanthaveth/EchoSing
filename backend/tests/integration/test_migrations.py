import asyncio

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "alembic_version",
    "songs",
    "song_assets",
    "song_analyses",
    "ingestion_jobs",
    "play_sessions",
    "line_scores",
}


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        names: list[str] = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    return set(names)


async def test_migrations_upgrade_downgrade_roundtrip(
    migrated_engine: AsyncEngine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    assert await _table_names(migrated_engine) == EXPECTED_TABLES

    await asyncio.to_thread(command.downgrade, config, "base")
    assert await _table_names(migrated_engine) == {"alembic_version"}

    await asyncio.to_thread(command.upgrade, config, "head")
    assert await _table_names(migrated_engine) == EXPECTED_TABLES
