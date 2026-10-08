"""Fixtures backed by a dedicated, migrated PostgreSQL test database.

The ``echosing_test`` database is created on demand next to the development
database and rebuilt from scratch with Alembic once per test run. Every test
runs inside a transaction that is rolled back afterwards.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from app.storage.dependencies import get_storage
from app.storage.local import LocalStorage

TEST_DATABASE_NAME = "echosing_test"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _ensure_database(admin_url: str, name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
async def test_database_url() -> str:
    dev_url = make_url(Settings(_env_file=None).database_url)
    await _ensure_database(
        dev_url.render_as_string(hide_password=False), TEST_DATABASE_NAME
    )
    return dev_url.set(database=TEST_DATABASE_NAME).render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session")
async def migrated_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    config = alembic_config(test_database_url)
    # Alembic's env.py calls asyncio.run(), so it must run outside this loop.
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(test_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
async def api_client(
    db_session: AsyncSession, storage: LocalStorage
) -> AsyncIterator[AsyncClient]:
    """Public API client bound to the test transaction and a temporary storage."""
    app = create_app(Settings(_env_file=None, cors_origins=["http://localhost:5173"]))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
