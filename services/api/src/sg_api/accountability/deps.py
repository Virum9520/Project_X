"""Dependencies for the accountability routes. Tests override these with in-memory fakes."""

import uuid
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select

from sg_core.accountability import (
    AccountabilityStore,
    CallDispatcher,
    DbRetentionSource,
    DispatchPolicy,
    RetentionSource,
    build_dispatcher,
    db_store,
    policy_from_settings,
)
from sg_core.db import get_sessionmaker
from sg_core.models.identity import User
from sg_core.settings import Settings, get_settings

DEFAULT_TZ = "America/New_York"


@dataclass(frozen=True, slots=True)
class UserRef:
    id: uuid.UUID
    timezone: str
    display_name: str | None = None


class UserDirectory(Protocol):
    async def resolve(self, clerk_user_id: str) -> UserRef | None:
        """Map a Clerk user ID (what tokens carry) to the `users` row."""
        ...


class DbUserDirectory:
    async def resolve(self, clerk_user_id: str) -> UserRef | None:
        async with get_sessionmaker()() as s:
            row = (
                await s.execute(
                    select(User.id, User.timezone, User.display_name).where(
                        User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None)
                    )
                )
            ).first()
        if row is None:
            return None
        return UserRef(row.id, row.timezone or DEFAULT_TZ, row.display_name)


def get_user_directory() -> UserDirectory:
    return DbUserDirectory()


def get_accountability_store() -> AccountabilityStore:
    return db_store()


def get_retention_source() -> RetentionSource:
    return DbRetentionSource(get_sessionmaker())


def get_policy(settings: Annotated[Settings, Depends(get_settings)]) -> DispatchPolicy:
    return policy_from_settings(settings)


def get_dispatcher(
    store: Annotated[AccountabilityStore, Depends(get_accountability_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    policy: Annotated[DispatchPolicy, Depends(get_policy)],
) -> CallDispatcher:
    return build_dispatcher(store, settings, policy)
