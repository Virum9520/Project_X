"""Alembic environment: async engine from `sg_core.settings`, metadata from `sg_core.models`."""

import asyncio
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from alembic.operations.ops import CreateTableOp, MigrationScript
from alembic.runtime.migration import MigrationContext
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DefaultClause, Enum, String, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from sg_core.models import Base
from sg_core.settings import get_settings

config = context.config
target_metadata = Base.metadata

# Objects TimescaleDB and pgvector manage themselves; autogenerate must not touch them.
_IGNORED_SCHEMAS = {"_timescaledb_cache", "_timescaledb_catalog", "_timescaledb_internal"}


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    if type_ == "table" and reflected and compare_to is None:
        schema = getattr(obj, "schema", None)
        # Only manage tables we model; ignore anything else living in the database.
        return schema not in _IGNORED_SCHEMAS and name in target_metadata.tables
    return True


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    """Render checked-VARCHAR enums as plain strings; their CHECK is rendered separately.

    Rendering `sa.Enum(create_constraint=True)` would create the CHECK a second time.
    """
    if type_ == "type" and isinstance(obj, Enum) and not obj.native_enum:
        return f"sa.String(length={obj.length})"
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector({obj.dim})"
    return False


def process_revision_directives(
    ctx: MigrationContext, revision: Any, directives: list[MigrationScript]
) -> None:
    """Swap checked-VARCHAR enum columns for plain strings in new tables.

    The table's convention-named CHECK is already in the op; leaving the `Enum` type in place
    would make Alembic emit a second, unconventionally named copy of it.
    """
    for script in directives:
        for op_ in script.upgrade_ops.ops if script.upgrade_ops else []:
            if not isinstance(op_, CreateTableOp):
                continue
            columns: list[Any] = []
            for item in op_.columns:
                if (
                    isinstance(item, Column)
                    and isinstance(item.type, Enum)
                    and not item.type.native_enum
                ):
                    # A fresh Column: copying one keeps the Enum's constraint-creating hook.
                    default = item.server_default
                    default_arg: Any = default.arg if isinstance(default, DefaultClause) else None
                    item = Column(
                        item.name,
                        String(length=item.type.length),
                        primary_key=item.primary_key,
                        nullable=item.nullable,
                        server_default=default_arg,
                    )
                columns.append(item)
            op_.columns = columns


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        render_item=render_item,
        process_revision_directives=process_revision_directives,
        compare_server_default=True,
        transaction_per_migration=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(
        url=get_settings().database_url.unicode_string(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        get_settings().database_url.unicode_string(), poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
