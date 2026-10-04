"""The seam between the routes and the data. Routes depend on `GardenService`, so tests swap in an
in-memory implementation; `DbGardenService` is the real one.

A learner is identified by their Clerk user id (`Learner.user_id`) and mapped to `users.id`. A
learner with no `users` row yet sees an empty garden, never an error.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_api.garden.analytics import Query, answer_metric
from sg_api.garden.ask import ask_sanjaya
from sg_api.garden.build import (
    build_dataset,
    build_memory,
    build_revisions,
    build_snapshot,
)
from sg_api.garden.data import (
    NO_USER,
    GardenData,
    load_garden_data,
    memory_rec,
    resolve_user_id,
)
from sg_api.garden.schemas import (
    AnalyticsOut,
    AskOut,
    GardenDatasetOut,
    GardenSnapshotOut,
    MemoryImpactOut,
    MemoryOut,
    RevisionOut,
)
from sg_core.db import get_sessionmaker
from sg_core.economics.budget import (
    BudgetExceededError,
    budget_hold,
    budget_key_for,
    monthly_limit_usd,
)
from sg_core.economics.usage import UsageContext
from sg_core.logging import get_logger
from sg_core.memory import MemoryNotFound, MemoryStore, garden_view
from sg_core.models.enums import CostCenter
from sg_core.providers import ProviderNotConfiguredError, llm_client_from_settings

log = get_logger(__name__)

# Reserved against the learner's monthly budget for one Ask Sanjaya answer.
ASK_HOLD_USD = Decimal("0.01")


class UnknownLearner(LookupError):
    """The caller has no `users` row, so they own no memories to change."""


class GardenService(Protocol):
    async def snapshot(self, learner: str, rev: int | None = None) -> GardenSnapshotOut: ...
    async def revisions(self, learner: str) -> list[RevisionOut]: ...
    async def dataset(self, learner: str) -> GardenDatasetOut: ...
    async def analytics(self, learner: str, metric: str, query: Query) -> AnalyticsOut: ...
    async def memories(self, learner: str) -> list[MemoryOut]: ...
    async def memory_impact(self, learner: str, memory_id: uuid.UUID) -> MemoryImpactOut: ...
    async def correct_memory(
        self, learner: str, memory_id: uuid.UUID, content: str
    ) -> MemoryOut: ...
    async def delete_memory(self, learner: str, memory_id: uuid.UUID) -> None: ...
    async def ask(self, learner: str, question: str) -> AskOut: ...


class DbGardenService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._maker = sessionmaker or get_sessionmaker()

    async def _load(self, session: AsyncSession, learner: str) -> tuple[uuid.UUID, GardenData]:
        user_id = await resolve_user_id(session, learner) or NO_USER
        return user_id, await load_garden_data(session, user_id, now=datetime.now(UTC))

    async def snapshot(self, learner: str, rev: int | None = None) -> GardenSnapshotOut:
        async with self._maker() as session:
            user_id, data = await self._load(session, learner)
            view = data.view if rev is None else await garden_view(session, user_id, rev=rev)
            return build_snapshot(data, view)

    async def revisions(self, learner: str) -> list[RevisionOut]:
        async with self._maker() as session:
            _, data = await self._load(session, learner)
            return build_revisions(data)

    async def dataset(self, learner: str) -> GardenDatasetOut:
        async with self._maker() as session:
            _, data = await self._load(session, learner)
            return build_dataset(data)

    async def analytics(self, learner: str, metric: str, query: Query) -> AnalyticsOut:
        async with self._maker() as session:
            _, data = await self._load(session, learner)
            return answer_metric(data, metric, query)

    async def memories(self, learner: str) -> list[MemoryOut]:
        async with self._maker() as session:
            user_id = await resolve_user_id(session, learner)
            if user_id is None:
                return []
            store = MemoryStore(session)
            return [
                build_memory(memory_rec(m, await store.impact(m)))
                for m in await store.list_active(user_id, limit=100)
            ]

    async def _owner(self, session: AsyncSession, learner: str) -> uuid.UUID:
        user_id = await resolve_user_id(session, learner)
        if user_id is None:
            raise UnknownLearner(learner)
        return user_id

    async def memory_impact(self, learner: str, memory_id: uuid.UUID) -> MemoryImpactOut:
        async with self._maker() as session:
            user_id = await self._owner(session, learner)
            store = MemoryStore(session)
            memory = next(
                (m for m in await store.list_active(user_id, limit=500) if m.id == memory_id),
                None,
            )
            if memory is None:
                raise MemoryNotFound(str(memory_id))
            return MemoryImpactOut(memory_id=str(memory_id), affects=await store.impact(memory))

    async def correct_memory(self, learner: str, memory_id: uuid.UUID, content: str) -> MemoryOut:
        async with self._maker() as session:
            user_id = await self._owner(session, learner)
            store = MemoryStore(session)
            revised = await store.correct(memory_id, user_id, content)
            out = build_memory(memory_rec(revised, await store.impact(revised)))
            await session.commit()
            return out

    async def delete_memory(self, learner: str, memory_id: uuid.UUID) -> None:
        async with self._maker() as session:
            user_id = await self._owner(session, learner)
            await MemoryStore(session).forget_private(memory_id, user_id)
            await session.commit()

    async def ask(self, learner: str, question: str) -> AskOut:
        async with self._maker() as session:
            user_id, data = await self._load(session, learner)
        usage = UsageContext(
            cost_center=CostCenter.LEARNER,
            component="ask_sanjaya",
            user_id=None if user_id == NO_USER else user_id,
        )
        try:
            llm = llm_client_from_settings()
        except ProviderNotConfiguredError:
            return await ask_sanjaya(data, question, None)
        async with llm:
            if user_id == NO_USER:  # nothing to ledger or budget: no model for an empty garden
                return await ask_sanjaya(data, question, None)
            try:
                async with budget_hold(
                    budget_key=budget_key_for(CostCenter.LEARNER, user_id),
                    amount_usd=ASK_HOLD_USD,
                    limit_usd=monthly_limit_usd(CostCenter.LEARNER),
                    cost_center=CostCenter.LEARNER,
                    user_id=user_id,
                ):
                    return await ask_sanjaya(data, question, llm, usage=usage)
            except BudgetExceededError:
                log.info("ask_sanjaya.budget_exceeded", user_id=str(user_id))
                return await ask_sanjaya(data, question, None)


def get_garden_service() -> GardenService:
    return DbGardenService()
