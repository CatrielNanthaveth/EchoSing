"""Declarative base and shared column types for the ORM models."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }
    # Fetch server-generated values (timestamps) with RETURNING right away, so
    # async code never triggers an implicit lazy load to read them.
    __mapper_args__ = {"eager_defaults": True}


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Map a ``StrEnum`` to a VARCHAR column guarded by a CHECK constraint.

    Values (not member names) are stored, and no native PostgreSQL enum type is
    created, so adding members later only requires replacing the constraint.

    Args:
        enum_cls: Enumeration to map.
        name: Constraint name suffix (becomes ``ck_<table>_<name>``).

    Returns:
        The SQLAlchemy column type.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
