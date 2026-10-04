"""Owner analytics views (migration 0004): static checks always, database checks opt-in.

The database tests need `SG_DB_TESTS=1` and a schema at `alembic upgrade head`; writes roll back.
"""

import importlib.util
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.settings import get_settings

MIGRATION = Path(__file__).parents[1] / "migrations" / "versions" / "0004_owner_analytics_views.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("m0004", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load()
VIEWS: dict[str, str] = M.VIEWS  # type: ignore[attr-defined]


def test_revision_chain() -> None:
    assert M.revision == "0004" and M.down_revision == "0003"  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", sorted(VIEWS))
def test_every_cost_view_reads_only_live_entries(name: str) -> None:
    body = VIEWS[name]
    if "cost_entries" in body:
        assert re.search(r"superseded_by_id\s+IS\s+NULL", body, re.IGNORECASE), name


@pytest.mark.parametrize("name", sorted(VIEWS))
def test_views_expose_no_personal_columns(name: str) -> None:
    body = VIEWS[name].lower()
    for forbidden in ("email", "phone", "transcript", "payload", "display_name", "raw"):
        assert forbidden not in body, f"{name} exposes {forbidden}"


def test_views_read_only_public_tables_by_qualified_name() -> None:
    for name, body in VIEWS.items():
        for table in re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", body, re.IGNORECASE):
            assert table.startswith("public.") or table == "s", (name, table)


pytestmark_db = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _entry(conn: AsyncConnection, kind: str, usd: str, component: str) -> object:
    return (
        await conn.execute(
            text(
                "INSERT INTO cost_entries (cost_center, component, provider, kind, native_amount, "
                "native_unit, usd_amount) VALUES ('developer', :c, 'test', :k, :u, 'usd', :u) "
                "RETURNING id"
            ),
            {"c": component, "k": kind, "u": usd},
        )
    ).scalar_one()


@pytestmark_db
async def test_cost_views_sum_only_live_entries(conn: AsyncConnection) -> None:
    component = "c22-view-test"
    estimated = await _entry(conn, "estimated", "1.000000", component)
    reconciled = await _entry(conn, "reconciled", "1.250000", component)
    await _entry(conn, "provider", "0.500000", component)
    await conn.execute(
        text("UPDATE cost_entries SET superseded_by_id = :r WHERE id = :e"),
        {"r": reconciled, "e": estimated},
    )
    live = (
        await conn.execute(
            text(
                "SELECT count(*), sum(usd_amount) FROM analytics.cost_entries_live "
                "WHERE component = :c"
            ),
            {"c": component},
        )
    ).one()
    assert (live[0], live[1]) == (2, 1.75)
    daily = (
        await conn.execute(
            text("SELECT sum(usd_total) FROM analytics.daily_cost WHERE component = :c"),
            {"c": component},
        )
    ).scalar_one()
    assert daily == 1.75  # the superseded 1.00 estimate is not added


@pytestmark_db
async def test_views_have_no_personal_columns(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'analytics' "
            "AND column_name ~* '(email|phone|name$|transcript|payload|raw)'"
        )
    )
    assert rows.all() == []


@pytestmark_db
async def test_readonly_role_reads_analytics_only(conn: AsyncConnection) -> None:
    role = (
        await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'sg_mcp_readonly'"))
    ).first()
    if role is None:
        pytest.skip("sg_mcp_readonly was not created (migration user lacked CREATEROLE)")

    async def can(obj: str, priv: str = "SELECT") -> bool:
        return bool(
            (
                await conn.execute(
                    text("SELECT has_table_privilege('sg_mcp_readonly', :o, :p)"),
                    {"o": obj, "p": priv},
                )
            ).scalar_one()
        )

    for view in VIEWS:
        assert await can(f"analytics.{view}")
        assert not await can(f"analytics.{view}", "INSERT")
    for table in ("public.users", "public.cost_entries", "public.sessions", "public.audit_log"):
        assert not await can(table)
    settings = (
        await conn.execute(text("SELECT rolconfig FROM pg_roles WHERE rolname = 'sg_mcp_readonly'"))
    ).scalar_one()
    assert "default_transaction_read_only=on" in settings
    assert any(s.startswith("statement_timeout=") for s in settings)
