"""Database-backed identity: grants, audit log, user/profile mirror and the capability catalogue.

Every store takes an `async_sessionmaker` and manages its own short transaction, so they work from
request handlers, middleware and the worker alike. Tests can pass a sessionmaker bound to a
connection in a rolled-back transaction.
"""

import ipaddress
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.identity.audit import AuditEvent
from sg_core.identity.capabilities import (
    CAPABILITY_DESCRIPTIONS,
    ROLE_CAPABILITIES,
    Capability,
)
from sg_core.identity.clerk import ClerkUser
from sg_core.identity.users import OnboardingFields, parse_onboarding
from sg_core.models.enums import ActorType, AdminStatus
from sg_core.models.identity import (
    AdminRoleGrant,
    AdminUser,
    AuditLog,
    Profile,
    RoleCapability,
    User,
)
from sg_core.models.identity import Capability as CapabilityRow

Sessions = async_sessionmaker[AsyncSession]

# Where `AuditEvent` fields without their own `audit_log` column are kept, inside `after`.
AUDIT_META_KEY = "_meta"


async def seed_identity_catalog(session: AsyncSession) -> None:
    """Idempotently upsert `capabilities` and the default `role_capabilities`.

    Descriptions are refreshed from code; role rows are only ever added, never removed, so an
    owner's manual additions survive. The caller commits.
    """
    stmt = insert(CapabilityRow).values(
        [{"key": c.value, "description": CAPABILITY_DESCRIPTIONS[c]} for c in Capability]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"description": stmt.excluded.description}
        )
    )
    rows = [
        {"role": role, "capability_key": cap.value}
        for role, caps in ROLE_CAPABILITIES.items()
        for cap in sorted(caps)
    ]
    await session.execute(insert(RoleCapability).values(rows).on_conflict_do_nothing())


async def seed_identity_catalog_committed(sessions: Sessions) -> None:
    async with sessions() as session, session.begin():
        await seed_identity_catalog(session)


class DbGrantStore:
    """Capabilities from active admins' unrevoked role grants (`admin_role_grants`)."""

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def capabilities_for(self, user_id: str) -> frozenset[Capability]:
        query = (
            select(RoleCapability.capability_key)
            .join(AdminRoleGrant, AdminRoleGrant.role == RoleCapability.role)
            .join(AdminUser, AdminUser.id == AdminRoleGrant.admin_user_id)
            .join(User, User.id == AdminUser.user_id)
            .where(
                User.clerk_user_id == user_id,
                User.deleted_at.is_(None),
                AdminUser.status == AdminStatus.ACTIVE,
                AdminRoleGrant.revoked_at.is_(None),
            )
            .distinct()
        )
        async with self._sessions() as session:
            keys = (await session.scalars(query)).all()
        known = {c.value: c for c in Capability}
        return frozenset(known[k] for k in keys if k in known)


class DbAuditSink:
    """Appends to `audit_log`. The actor is resolved from the Clerk ID when we have a `users` row.

    Fields without a column (status code, actor Clerk ID and email) go under `after["_meta"]`.
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def record(self, event: AuditEvent) -> None:
        raw_target = event.target or ""
        target_type, sep, target_id = raw_target.partition(":")
        if not sep:  # no "type:id" shape: keep the whole value as the type
            target_type, target_id = raw_target, ""
        meta: dict[str, Any] = {
            "status_code": event.status_code,
            "actor_clerk_user_id": event.actor_id,
            "actor_email": event.actor_email,
        }
        async with self._sessions() as session, session.begin():
            actor = await session.scalar(
                select(User.id).where(User.clerk_user_id == event.actor_id)
            )
            session.add(
                AuditLog(
                    occurred_at=event.occurred_at,
                    actor_user_id=actor,
                    actor_type=ActorType.ADMIN,
                    action=event.action[:100],
                    target_type=target_type[:64] or None,
                    target_id=target_id[:128] or None,
                    request_id=event.request_id[:64] or None,
                    before=event.before,
                    after={**(event.after or {}), AUDIT_META_KEY: meta},
                    ip=_valid_ip(event.ip),
                    user_agent=event.user_agent,
                )
            )


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


class DbUserStore:
    """Mirrors a Clerk user into `users`, and onboarding answers into `profiles`.

    Clerk stays the source of truth. A user without a verified primary email is skipped (`users`
    requires one). Unchanged data causes no write.
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def sync(self, user: ClerkUser) -> None:
        if user.primary_email is None:
            return
        onboarding = parse_onboarding(user.onboarding)
        timezone = onboarding.timezone if onboarding else None
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(User).where(User.clerk_user_id == user.id))
            if row is None:
                user_id = await session.scalar(
                    insert(User)
                    .values(
                        clerk_user_id=user.id,
                        email=user.primary_email,
                        display_name=user.display_name,
                        timezone=timezone,
                    )
                    .on_conflict_do_update(
                        index_elements=["clerk_user_id"],
                        set_={"email": user.primary_email, "deleted_at": None},
                    )
                    .returning(User.id)
                )
            else:
                user_id = row.id
                if row.email != user.primary_email:
                    row.email = user.primary_email
                if user.display_name and row.display_name != user.display_name:
                    row.display_name = user.display_name
                if timezone and row.timezone != timezone:
                    row.timezone = timezone
                if row.deleted_at is not None:
                    row.deleted_at = None
            if onboarding is not None and user_id is not None:
                await _upsert_profile(session, user_id, onboarding)


async def _upsert_profile(
    session: AsyncSession, user_id: uuid.UUID, onboarding: OnboardingFields
) -> None:
    profile = await session.get(Profile, user_id)
    if profile is None:
        await session.execute(
            insert(Profile)
            .values(
                user_id=user_id,
                major=onboarding.major,
                experience_level=onboarding.experience_level,
                goals=onboarding.goals,
                onboarded_at=onboarding.onboarded_at,
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        return
    if profile.major != onboarding.major:
        profile.major = onboarding.major
    if profile.experience_level != onboarding.experience_level:
        profile.experience_level = onboarding.experience_level
    if profile.goals != onboarding.goals:
        profile.goals = onboarding.goals
    if profile.onboarded_at != onboarding.onboarded_at:
        profile.onboarded_at = onboarding.onboarded_at
