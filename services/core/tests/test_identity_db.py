"""DB-backed identity against a real database at DATABASE_URL (schema at `alembic upgrade head`).

Opt-in with `SG_DB_TESTS=1`. Every write is rolled back.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.identity import AuditEvent, Capability
from sg_core.identity.clerk import ClerkUser
from sg_core.identity.db import (
    AUDIT_META_KEY,
    DbAuditSink,
    DbGrantStore,
    DbUserStore,
    seed_identity_catalog,
)
from sg_core.models.enums import AdminRole, AdminStatus
from sg_core.models.identity import (
    AdminRoleGrant,
    AdminUser,
    AuditLog,
    Profile,
    RoleCapability,
    User,
)
from sg_core.models.identity import Capability as CapabilityRow
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

CLERK_ID = "user_c01_dbtest"
EMAIL = "c01-dbtest@example.com"

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
async def sessions() -> AsyncIterator[Sessions]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield async_sessionmaker(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
        finally:
            await transaction.rollback()
    await engine.dispose()


def _clerk_user(**overrides: object) -> ClerkUser:
    values: dict[str, object] = {
        "id": CLERK_ID,
        "primary_email": EMAIL,
        "two_factor_enabled": True,
        "display_name": "Test Learner",
    }
    return ClerkUser(**(values | overrides))  # type: ignore[arg-type]


ONBOARDING = {
    "major": "Computer Science",
    "goals": ["job-search"],
    "experience": "coursework",
    "timezone": "America/Detroit",
    "completedAt": "2026-10-04T12:00:00Z",
}


async def test_seed_is_idempotent_and_complete(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        await seed_identity_catalog(session)
        await seed_identity_catalog(session)
        keys = set(await session.scalars(select(CapabilityRow.key)))
        owner = set(
            await session.scalars(
                select(RoleCapability.capability_key).where(RoleCapability.role == AdminRole.OWNER)
            )
        )
    assert {c.value for c in Capability} <= keys
    assert owner >= {c.value for c in Capability}


async def test_user_sync_creates_and_mirrors_onboarding(sessions: Sessions) -> None:
    store = DbUserStore(sessions)
    await store.sync(_clerk_user())  # signed up, not onboarded yet
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.clerk_user_id == CLERK_ID))
        assert user is not None and user.email == EMAIL
        assert await session.get(Profile, user.id) is None

    await store.sync(_clerk_user(onboarding=ONBOARDING))
    await store.sync(_clerk_user(onboarding=ONBOARDING))  # idempotent
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.clerk_user_id == CLERK_ID))
        assert user is not None and user.timezone == "America/Detroit"
        profile = await session.get(Profile, user.id)
        assert profile is not None
        assert (profile.major, profile.experience_level, profile.goals) == (
            "Computer Science",
            "coursework",
            ["job-search"],
        )
        assert profile.onboarded_at == datetime(2026, 10, 4, 12, tzinfo=UTC)
        count = await session.scalar(
            select(func.count()).select_from(User).where(User.clerk_user_id == CLERK_ID)
        )
        assert count == 1

    await store.sync(_clerk_user(onboarding={**ONBOARDING, "major": "Math"}))
    async with sessions() as session:
        profile = await session.scalar(select(Profile).join(User).where(User.email == EMAIL))
        assert profile is not None and profile.major == "Math"


async def test_user_without_verified_email_is_skipped(sessions: Sessions) -> None:
    await DbUserStore(sessions).sync(_clerk_user(primary_email=None))
    async with sessions() as session:
        assert await session.scalar(select(User).where(User.clerk_user_id == CLERK_ID)) is None


async def test_grants_follow_roles_and_revocation(sessions: Sessions) -> None:
    await DbUserStore(sessions).sync(_clerk_user())
    grants = DbGrantStore(sessions)
    async with sessions() as session, session.begin():
        await seed_identity_catalog(session)
    assert await grants.capabilities_for(CLERK_ID) == frozenset()

    async with sessions() as session, session.begin():
        user_id = await session.scalar(select(User.id).where(User.clerk_user_id == CLERK_ID))
        assert user_id is not None
        admin = AdminUser(user_id=user_id)
        session.add(admin)
        await session.flush()
        session.add(AdminRoleGrant(admin_user_id=admin.id, role=AdminRole.ANALYST))
        session.add(
            AdminRoleGrant(
                admin_user_id=admin.id, role=AdminRole.DEVELOPER, revoked_at=datetime.now(UTC)
            )
        )
    caps = await grants.capabilities_for(CLERK_ID)
    assert Capability.CONSOLE_ACCESS in caps and Capability.USERS_READ in caps
    assert Capability.AUDIT_READ not in caps  # only the revoked developer role carries it
    assert Capability.GRANTS_MANAGE not in caps

    async with sessions() as session, session.begin():
        admin_row = await session.scalar(select(AdminUser).where(AdminUser.user_id == user_id))
        assert admin_row is not None
        admin_row.status = AdminStatus.DISABLED
    assert await grants.capabilities_for(CLERK_ID) == frozenset()
    assert await grants.capabilities_for("user_nobody") == frozenset()


async def test_sync_never_undeletes_a_soft_deleted_user(sessions: Sessions) -> None:
    store = DbUserStore(sessions)
    await store.sync(_clerk_user())
    async with sessions() as session, session.begin():
        await seed_identity_catalog(session)
        user = await session.scalar(select(User).where(User.clerk_user_id == CLERK_ID))
        assert user is not None
        admin = AdminUser(user_id=user.id)
        session.add(admin)
        await session.flush()
        session.add(AdminRoleGrant(admin_user_id=admin.id, role=AdminRole.ANALYST))
        user.deleted_at = datetime.now(UTC)

    await store.sync(_clerk_user(onboarding=ONBOARDING))  # e.g. their next admin request
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.clerk_user_id == CLERK_ID))
        assert user is not None and user.deleted_at is not None
    assert await DbGrantStore(sessions).capabilities_for(CLERK_ID) == frozenset()


async def test_audit_sink_writes_audit_log(sessions: Sessions) -> None:
    await DbUserStore(sessions).sync(_clerk_user())
    sink = DbAuditSink(sessions)
    await sink.record(
        AuditEvent(
            actor_id=CLERK_ID,
            actor_email=EMAIL,
            action="POST /v1/admin/things/{id}",
            request_id="req-c01-db-1",
            status_code=200,
            target="thing:42",
            before={"v": 1},
            after={"v": 2},
            ip="203.0.113.7",
            user_agent="pytest",
        )
    )
    await sink.record(  # unknown actor, junk ip, untyped target
        AuditEvent(
            actor_id="user_unknown",
            actor_email=None,
            action="DELETE /v1/admin/x",
            request_id="req-c01-db-2",
            status_code=403,
            target="whole-thing",
            ip="not-an-ip",
        )
    )
    async with sessions() as session:
        rows = {
            r.request_id: r
            for r in await session.scalars(
                select(AuditLog).where(AuditLog.request_id.like("req-c01-db-%"))
            )
        }
        user_id = await session.scalar(select(User.id).where(User.clerk_user_id == CLERK_ID))
    first, second = rows["req-c01-db-1"], rows["req-c01-db-2"]
    assert first.actor_user_id == user_id
    assert (first.target_type, first.target_id) == ("thing", "42")
    assert first.before == {"v": 1}
    assert first.after is not None and first.after["v"] == 2
    assert first.after[AUDIT_META_KEY]["status_code"] == 200
    assert str(first.ip) == "203.0.113.7" and first.user_agent == "pytest"
    assert second.actor_user_id is None
    assert (second.target_type, second.target_id) == ("whole-thing", None)
    assert second.ip is None
    assert second.after is not None and second.after[AUDIT_META_KEY]["status_code"] == 403
