from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateTable

from app.db import models
from app.db.base import Base
from app.domain.enums import IngestionStage


def _ddl(table_name: str) -> str:
    table = Base.metadata.tables[table_name]
    # Creating an engine never connects; it is only used for its dialect.
    dialect = create_async_engine("postgresql+asyncpg://").dialect
    return str(CreateTable(table).compile(dialect=dialect))


def test_all_tables_are_registered() -> None:
    assert models.Song.__tablename__ in Base.metadata.tables
    assert set(Base.metadata.tables) == {
        "songs",
        "song_assets",
        "song_analyses",
        "ingestion_jobs",
        "play_sessions",
        "line_scores",
    }


def test_constraints_follow_naming_convention() -> None:
    ddl = _ddl("songs")

    assert "CONSTRAINT pk_songs PRIMARY KEY" in ddl
    assert "CONSTRAINT ck_songs_song_status CHECK" in ddl


def test_enum_columns_store_values_not_names() -> None:
    ddl = _ddl("ingestion_jobs")

    assert "'extracting_pitch'" in ddl
    assert "'EXTRACTING_PITCH'" not in ddl


def test_terminal_ingestion_stages() -> None:
    terminal = {stage for stage in IngestionStage if stage.is_terminal}

    assert terminal == {IngestionStage.DONE, IngestionStage.FAILED}
