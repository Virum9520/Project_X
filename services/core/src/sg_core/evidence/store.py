"""Persistence seam of the evidence pipeline.

`EvidenceStore` is what the pipeline needs from storage. `DbEvidenceStore` (db_store.py) is the
real thing; `InMemoryEvidenceStore` below keeps the same rules for fast, database-free tests.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sg_core.evidence.types import ConceptInfo
from sg_core.memory import NewMemory
from sg_core.models.enums import (
    AssessmentOutcome,
    AssessmentStatus,
    Assistance,
    Character,
    MemoryStatus,
    SessionStatus,
)
from sg_core.rules import GardenState, Observation, RulesResult


class StaleGardenError(RuntimeError):
    """Another writer committed a garden revision first. Reload the state and retry."""


@dataclass(slots=True)
class SessionRef:
    id: uuid.UUID
    user_id: uuid.UUID
    character: str
    mode: str
    conversation_id: str | None
    is_test: bool = False
    status: str = SessionStatus.CREATED.value
    started_at: datetime | None = None
    ended_at: datetime | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NewEvidence:
    concept_key: str
    dimension: str
    assistance: Assistance
    kind: str  # quote | answer | code_run | teach_back
    quote: str
    occurred_at: datetime
    dedupe_key: str
    transcript_start_s: float | None = None
    problem_family: str | None = None


@dataclass(frozen=True, slots=True)
class NewAssessment:
    concept_key: str
    dimension: str
    outcome: AssessmentOutcome
    assistance: Assistance
    uncertainty: float | None
    rationale: str
    judge_model: str
    evidence: tuple[NewEvidence, ...]
    status: AssessmentStatus = AssessmentStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class SavedAssessment:
    id: uuid.UUID
    rev: int
    evidence_ids: tuple[uuid.UUID, ...]
    occurred_at: datetime | None
    problem_family: str | None
    supersedes: uuid.UUID | None = None  # set when this re-judges an earlier assessment


@dataclass(frozen=True, slots=True)
class ProvisionalMemory:
    memory_id: uuid.UUID
    concept_key: str
    dimension: str
    outcome: str | None  # the micro-judge's read, if there was one


@dataclass(frozen=True, slots=True)
class GardenSnapshotState:
    state: GardenState
    rev: int


class EvidenceStore(Protocol):
    async def resolve_user(self, clerk_user_id: str) -> uuid.UUID | None: ...
    async def is_demo_account(self, user_id: uuid.UUID) -> bool: ...
    async def catalog(self) -> dict[str, ConceptInfo]: ...
    async def dimension_rubrics(self) -> dict[str, dict[str, Any]]: ...

    async def find_session(self, conversation_id: str) -> SessionRef | None: ...
    async def ensure_session(
        self,
        *,
        user_id: uuid.UUID,
        character: Character,
        mode: str,
        conversation_id: str | None,
        public_session_id: str | None,
        now: datetime,
    ) -> SessionRef: ...
    async def patch_session(
        self,
        session_id: uuid.UUID,
        *,
        status: SessionStatus | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None: ...

    async def hinted_concepts(self, session_id: uuid.UUID) -> set[str | None]: ...
    async def retention_concept(self, user_id: uuid.UUID, conversation_id: str) -> str | None: ...
    async def provisional_memories(self, session_id: uuid.UUID) -> list[ProvisionalMemory]: ...

    async def add_evidence(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewEvidence
    ) -> uuid.UUID: ...
    async def save_assessment(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewAssessment
    ) -> SavedAssessment: ...
    async def set_assessment_status(
        self, assessment_ids: list[uuid.UUID], status: AssessmentStatus
    ) -> None: ...
    async def accepted_observations(self, user_id: uuid.UUID) -> list[Observation]: ...

    async def garden_state(self, user_id: uuid.UUID) -> GardenSnapshotState: ...
    async def commit_garden(
        self,
        user_id: uuid.UUID,
        *,
        expected_rev: int,
        result: RulesResult,
        reason: str,
        now: datetime,
    ) -> int: ...

    async def append_memory(self, new: NewMemory) -> uuid.UUID: ...
    async def promote_memory(
        self, memory_id: uuid.UUID, user_id: uuid.UUID, evidence_ids: list[uuid.UUID]
    ) -> None: ...
    async def dispute_memory(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> None: ...
    async def emit(
        self, session_id: uuid.UUID, user_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None: ...


# ── In-memory implementation (tests and local runs without a database) ──
@dataclass(slots=True)
class _Evidence:
    id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    item: NewEvidence


@dataclass(slots=True)
class _Assessment:
    id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    rev: int
    item: NewAssessment
    evidence_ids: tuple[uuid.UUID, ...]
    status: AssessmentStatus
    supersedes: uuid.UUID | None = None


@dataclass(slots=True)
class _Memory:
    id: uuid.UUID
    new: NewMemory
    status: MemoryStatus


class InMemoryEvidenceStore:
    """Mirrors `DbEvidenceStore`'s rules: dedupe keys, assessment revisions, optimistic garden
    revisions, append-only memory. Public attributes are there for assertions."""

    def __init__(
        self,
        catalog: dict[str, ConceptInfo] | None = None,
        *,
        users: dict[str, uuid.UUID] | None = None,
        demo_users: set[uuid.UUID] | None = None,
        dimension_rubrics: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._catalog = catalog or {}
        self._dimension_rubrics = dimension_rubrics or {}
        self.users = users or {}
        self.demo_users = demo_users or set()
        self.sessions: dict[uuid.UUID, SessionRef] = {}
        self.hints: dict[uuid.UUID, set[str | None]] = {}
        self.retention: dict[str, str] = {}  # conversation id -> concept key
        self.evidence: dict[uuid.UUID, _Evidence] = {}
        self.assessments: dict[uuid.UUID, _Assessment] = {}
        self.memories: dict[uuid.UUID, _Memory] = {}
        self.revisions: list[dict[str, Any]] = []
        self.plants: dict[uuid.UUID, dict[str, Any]] = {}
        self.events: list[tuple[uuid.UUID, str, dict[str, Any]]] = []
        self._state: dict[uuid.UUID, GardenState] = {}
        self.fail_commits = 0  # raise StaleGardenError this many times (concurrency tests)

    async def resolve_user(self, clerk_user_id: str) -> uuid.UUID | None:
        return self.users.get(clerk_user_id)

    async def is_demo_account(self, user_id: uuid.UUID) -> bool:
        return user_id in self.demo_users

    async def catalog(self) -> dict[str, ConceptInfo]:
        return dict(self._catalog)

    async def dimension_rubrics(self) -> dict[str, dict[str, Any]]:
        return dict(self._dimension_rubrics)

    async def find_session(self, conversation_id: str) -> SessionRef | None:
        return next(
            (s for s in self.sessions.values() if s.conversation_id == conversation_id), None
        )

    async def ensure_session(
        self,
        *,
        user_id: uuid.UUID,
        character: Character,
        mode: str,
        conversation_id: str | None,
        public_session_id: str | None,
        now: datetime,
    ) -> SessionRef:
        if conversation_id:
            found = await self.find_session(conversation_id)
            if found is not None:
                return found
        ref = SessionRef(
            id=uuid.uuid4(),
            user_id=user_id,
            character=character.value,
            mode=mode,
            conversation_id=conversation_id,
            status=SessionStatus.ACTIVE.value,
            started_at=now,
            attributes={"public_session_id": public_session_id} if public_session_id else {},
        )
        self.sessions[ref.id] = ref
        return ref

    async def patch_session(
        self,
        session_id: uuid.UUID,
        *,
        status: SessionStatus | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        ref = self.sessions[session_id]
        if status is not None:
            ref.status = status.value
        ref.started_at = started_at or ref.started_at
        ref.ended_at = ended_at or ref.ended_at
        if attributes:
            ref.attributes = {**ref.attributes, **attributes}

    async def hinted_concepts(self, session_id: uuid.UUID) -> set[str | None]:
        return set(self.hints.get(session_id, set()))

    async def retention_concept(self, user_id: uuid.UUID, conversation_id: str) -> str | None:
        return self.retention.get(conversation_id)

    async def provisional_memories(self, session_id: uuid.UUID) -> list[ProvisionalMemory]:
        out: list[ProvisionalMemory] = []
        for m in self.memories.values():
            d = m.new.data
            if (
                m.new.source_session_id == session_id
                and m.new.kind == "provisional_growth"
                and m.status is MemoryStatus.PROVISIONAL
            ):
                out.append(
                    ProvisionalMemory(m.id, d["concept_key"], d["dimension"], d.get("outcome"))
                )
        return out

    async def add_evidence(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewEvidence
    ) -> uuid.UUID:
        for e in self.evidence.values():
            if e.item.dedupe_key == item.dedupe_key:
                return e.id
        row = _Evidence(uuid.uuid4(), user_id, session_id, item)
        self.evidence[row.id] = row
        return row.id

    async def save_assessment(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewAssessment
    ) -> SavedAssessment:
        ids = tuple([await self.add_evidence(user_id, session_id, e) for e in item.evidence])
        previous = [
            a
            for a in self.assessments.values()
            if a.session_id == session_id
            and a.item.concept_key == item.concept_key
            and a.item.dimension == item.dimension
        ]
        # The same verdict again (a replayed job) is not a new revision.
        for p in previous:
            if p.status is not AssessmentStatus.SUPERSEDED and _same(p, item, ids):
                return _saved(p, self.evidence)
        latest = max(previous, key=lambda a: a.rev, default=None)
        if latest is not None:
            latest.status = AssessmentStatus.SUPERSEDED
        row = _Assessment(
            id=uuid.uuid4(),
            user_id=user_id,
            session_id=session_id,
            rev=(latest.rev + 1) if latest else 1,
            item=item,
            evidence_ids=ids,
            status=item.status,
            supersedes=latest.id if latest else None,
        )
        self.assessments[row.id] = row
        return _saved(row, self.evidence)

    async def set_assessment_status(
        self, assessment_ids: list[uuid.UUID], status: AssessmentStatus
    ) -> None:
        for i in assessment_ids:
            self.assessments[i].status = status

    async def accepted_observations(self, user_id: uuid.UUID) -> list[Observation]:
        out: list[Observation] = []
        for a in self.assessments.values():
            if a.user_id != user_id or a.status is not AssessmentStatus.ACCEPTED:
                continue
            saved = _saved(a, self.evidence)
            out.append(
                Observation(
                    assessment_id=a.id,
                    concept_key=a.item.concept_key,
                    dimension=a.item.dimension,
                    outcome=a.item.outcome,
                    assistance=a.item.assistance,
                    occurred_at=saved.occurred_at or datetime(1970, 1, 1, tzinfo=UTC),
                    evidence_ids=a.evidence_ids,
                    uncertainty=a.item.uncertainty,
                    problem_family=saved.problem_family,
                )
            )
        return out

    async def garden_state(self, user_id: uuid.UUID) -> GardenSnapshotState:
        rev = max((r["rev"] for r in self.revisions if r["user_id"] == user_id), default=0)
        return GardenSnapshotState(self._state.get(user_id, GardenState()), rev)

    async def commit_garden(
        self,
        user_id: uuid.UUID,
        *,
        expected_rev: int,
        result: RulesResult,
        reason: str,
        now: datetime,
    ) -> int:
        current = (await self.garden_state(user_id)).rev
        if self.fail_commits > 0:
            self.fail_commits -= 1
            raise StaleGardenError("garden moved")
        if current != expected_rev:
            raise StaleGardenError(f"expected rev {expected_rev}, garden is at {current}")
        rev = current + 1
        self.revisions.append(
            {
                "user_id": user_id,
                "rev": rev,
                "rule_ver": result.rule_version,
                "assessment_ids": list(result.assessment_ids),
                "reason": reason,
                "changes": result.to_revision_changes(),
            }
        )
        self._state[user_id] = result.state
        for change in result.changes:
            self.plants[user_id] = {
                **self.plants.get(user_id, {}),
                change.concept_key: change.after,
            }
        return rev

    async def append_memory(self, new: NewMemory) -> uuid.UUID:
        row = _Memory(uuid.uuid4(), new, new.status)
        self.memories[row.id] = row
        return row.id

    async def promote_memory(
        self, memory_id: uuid.UUID, user_id: uuid.UUID, evidence_ids: list[uuid.UUID]
    ) -> None:
        old = self.memories[memory_id]
        old.status = MemoryStatus.SUPERSEDED
        merged = list(dict.fromkeys([*old.new.evidence_ids, *evidence_ids]))
        promoted = NewMemory(
            user_id=user_id,
            layer=old.new.layer,
            kind=old.new.kind,
            content=old.new.content,
            source=old.new.source,
            source_character=old.new.source_character,
            source_session_id=old.new.source_session_id,
            evidence_ids=merged,
            status=MemoryStatus.ACCEPTED,
            data={**old.new.data, "promoted_from": str(memory_id)},
        )
        await self.append_memory(promoted)

    async def dispute_memory(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.memories[memory_id].status = MemoryStatus.DISPUTED

    async def emit(
        self, session_id: uuid.UUID, user_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.events.append((session_id, event_type, payload))


def _same(row: _Assessment, item: NewAssessment, ids: tuple[uuid.UUID, ...]) -> bool:
    return (
        row.item.outcome == item.outcome
        and row.item.assistance == item.assistance
        and row.item.judge_model == item.judge_model
        and row.evidence_ids == ids
    )


def _saved(row: _Assessment, evidence: dict[uuid.UUID, _Evidence]) -> SavedAssessment:
    cited = [evidence[i].item for i in row.evidence_ids if i in evidence]
    return SavedAssessment(
        id=row.id,
        rev=row.rev,
        evidence_ids=row.evidence_ids,
        occurred_at=max((c.occurred_at for c in cited), default=None),
        problem_family=next((c.problem_family for c in cited if c.problem_family), None),
        supersedes=row.supersedes,
    )
