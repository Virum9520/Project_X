"""Postgres `EvidenceStore`. It works inside the caller's session and transaction.

The provider-event handler passes its savepointed session, so evidence, assessments, the garden
revision, memories and the outbox events either all commit with the event's `processed` status or
all roll back. Garden revisions take a per-learner advisory lock and check `expected_rev`, so two
sessions finishing at once cannot both write the same revision or overwrite each other.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.evidence.store import (
    GardenSnapshotState,
    NewAssessment,
    NewEvidence,
    ProvisionalMemory,
    SavedAssessment,
    SessionRef,
    StaleGardenError,
)
from sg_core.evidence.types import CodeRun, ConceptInfo, RubricInfo
from sg_core.memory import MemoryStore, NewMemory
from sg_core.models.accountability import CallAttempt, CallOccurrence
from sg_core.models.curriculum import Concept, Curriculum, Rubric
from sg_core.models.enums import (
    AssessmentOutcome,
    AssessmentStatus,
    Assistance,
    Character,
    CurriculumStatus,
    EventSource,
    MemoryStatus,
    SessionStatus,
)
from sg_core.models.evidence import (
    Assessment,
    EvidenceItem,
    GardenRevision,
)
from sg_core.models.evidence import PlantState as PlantRow
from sg_core.models.identity import User
from sg_core.models.memory import Memory
from sg_core.models.sessions import HintGiven, SandboxRun, SessionEvent
from sg_core.models.sessions import Session as SessionRow
from sg_core.rules import GardenState, Observation, PlantState, RulesResult
from sg_core.settings import get_settings

BHIMA_MODE = "accountability_call"
PROVISIONAL_KIND = "provisional_growth"
RETENTION_KIND = "retention_check"


def _ref(row: SessionRow) -> SessionRef:
    return SessionRef(
        id=row.id,
        user_id=row.user_id,
        character=row.character.value,
        mode=row.mode,
        conversation_id=row.el_conversation_id,
        is_test=row.is_test,
        status=row.status.value,
        started_at=row.started_at,
        ended_at=row.ended_at,
        attributes=dict(row.attributes or {}),
    )


class DbEvidenceStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._catalog: dict[str, ConceptInfo] | None = None

    # ── identity and curriculum ──
    async def resolve_user(self, clerk_user_id: str) -> uuid.UUID | None:
        return await self.session.scalar(
            select(User.id).where(User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None))
        )

    async def is_demo_account(self, user_id: uuid.UUID) -> bool:
        emails = get_settings().demo_account_emails
        if not emails:
            return False
        email = await self.session.scalar(select(User.email).where(User.id == user_id))
        return email is not None and email.lower() in emails

    async def catalog(self) -> dict[str, ConceptInfo]:
        if self._catalog is not None:
            return self._catalog
        rows = (
            await self.session.execute(
                select(Concept)
                .join(Curriculum, Curriculum.id == Concept.curriculum_id)
                .where(Curriculum.status == CurriculumStatus.ACTIVE)
            )
        ).scalars()
        concepts = list(rows)
        rubrics: dict[uuid.UUID, Rubric] = {}
        if concepts:
            for r in (
                await self.session.execute(
                    select(Rubric)
                    .where(Rubric.concept_id.in_([c.id for c in concepts]))
                    .order_by(Rubric.version)
                )
            ).scalars():
                if r.concept_id is not None and r.dimension is None:
                    rubrics[r.concept_id] = r  # ascending order: the newest version wins
        self._catalog = {
            c.key: ConceptInfo(
                id=c.id,
                key=c.key,
                title=c.title,
                domain=c.domain,
                summary=c.summary,
                rubric=(
                    RubricInfo(
                        rubrics[c.id].id, rubrics[c.id].version, dict(rubrics[c.id].criteria)
                    )
                    if c.id in rubrics
                    else None
                ),
            )
            for c in concepts
        }
        return self._catalog

    async def dimension_rubrics(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rows = await self.session.execute(
            select(Rubric)
            .where(Rubric.concept_id.is_(None), Rubric.dimension.is_not(None))
            .order_by(Rubric.version)
        )
        for r in rows.scalars():
            if r.dimension is not None:
                out[r.dimension.value] = dict(r.criteria)
        return out

    # ── sessions ──
    async def _by_conversation(self, conversation_id: str) -> SessionRef | None:
        row = await self.session.scalar(
            select(SessionRow).where(SessionRow.el_conversation_id == conversation_id)
        )
        return _ref(row) if row is not None else None

    async def find_session(self, conversation_id: str) -> SessionRef | None:
        found = await self._by_conversation(conversation_id)
        if found is not None:
            return found
        # A Bhima call is dispatched by the accountability scheduler, not by POST /v1/sessions:
        # its attempt knows the conversation and the learner. Create its session row on first
        # sight so its evidence has a home.
        attempt = await self.session.scalar(
            select(CallAttempt).where(CallAttempt.el_conversation_id == conversation_id)
        )
        if attempt is None:
            return None
        user_id = await self.session.scalar(
            select(CallOccurrence.user_id).where(CallOccurrence.id == attempt.occurrence_id)
        )
        if user_id is None:  # a Call-now test call has no learner: no evidence
            return None
        ref = await self.ensure_session(
            user_id=user_id,
            character=Character.BHIMA,
            mode=BHIMA_MODE,
            conversation_id=conversation_id,
            public_session_id=None,
            now=attempt.connected_at or attempt.created_at,
        )
        if attempt.session_id is None:
            await self.session.execute(
                update(CallAttempt).where(CallAttempt.id == attempt.id).values(session_id=ref.id)
            )
        return ref

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
            existing = await self._by_conversation(conversation_id)
            if existing is not None:
                return existing
        curriculum_id = await self.session.scalar(
            select(Curriculum.id).where(Curriculum.status == CurriculumStatus.ACTIVE).limit(1)
        )
        row = SessionRow(
            user_id=user_id,
            character=character,
            mode=mode,
            status=SessionStatus.ACTIVE,
            el_conversation_id=conversation_id,
            curriculum_id=curriculum_id,
            started_at=now,
            attributes={"public_session_id": public_session_id} if public_session_id else {},
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:  # a concurrent tool call created it first
            self.session.expunge(row)
            if conversation_id:
                found = await self.session.scalar(
                    select(SessionRow).where(SessionRow.el_conversation_id == conversation_id)
                )
                if found is not None:
                    return _ref(found)
            raise
        return _ref(row)

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
        row = await self.session.get(SessionRow, session_id, with_for_update=True)
        if row is None:
            raise LookupError(f"session {session_id} not found")
        if status is not None:
            row.status = status
        row.started_at = row.started_at or started_at
        if ended_at is not None:
            row.ended_at = ended_at
        if duration_seconds is not None:
            row.duration_seconds = duration_seconds
        if attributes:
            row.attributes = {**(row.attributes or {}), **attributes}
        await self.session.flush()

    # ── context for the judge ──
    async def hinted_concepts(self, session_id: uuid.UUID) -> set[str | None]:
        rows = await self.session.execute(
            select(Concept.key)
            .select_from(HintGiven)
            .outerjoin(Concept, Concept.id == HintGiven.concept_id)
            .where(HintGiven.session_id == session_id)
        )
        return set(rows.scalars())

    async def retention_concept(self, user_id: uuid.UUID, conversation_id: str) -> str | None:
        attempt_id = await self.session.scalar(
            select(CallAttempt.id).where(CallAttempt.el_conversation_id == conversation_id)
        )
        if attempt_id is None:
            return None
        data = await self.session.scalar(
            select(Memory.data)
            .where(
                Memory.user_id == user_id,
                Memory.kind == RETENTION_KIND,
                Memory.data["attempt_id"].astext == str(attempt_id),
            )
            .order_by(Memory.created_at.desc())
            .limit(1)
        )
        key = data.get("concept_key") if isinstance(data, dict) else None
        return key if isinstance(key, str) else None

    async def code_runs(self, session_id: uuid.UUID) -> list[CodeRun]:
        rows = await self.session.execute(
            select(EvidenceItem, SandboxRun, Concept.key)
            .join(Concept, Concept.id == EvidenceItem.concept_id)
            .join(SandboxRun, SandboxRun.id == EvidenceItem.sandbox_run_id)
            .where(EvidenceItem.session_id == session_id, EvidenceItem.kind == "code_run")
            .order_by(EvidenceItem.occurred_at, EvidenceItem.created_at)
        )
        return [
            CodeRun(
                concept_key=key,
                status=run.status.value,
                passed=run.tests_passed or 0,
                total=run.tests_total or 0,
                assistance=Assistance(ev.assistance),
                quote=ev.quote or "",
                occurred_at=ev.occurred_at,
                dedupe_key=ev.dedupe_key,
                problem_family=ev.problem_family,
                hint_count=len(ev.hint_ids or []),
                run_id=run.id,
                snapshot_id=ev.code_snapshot_id,
                evidence_id=ev.id,
            )
            for ev, run, key in rows.all()
        ]

    async def provisional_memories(self, session_id: uuid.UUID) -> list[ProvisionalMemory]:
        rows = await self.session.scalars(
            select(Memory)
            .where(
                Memory.source_session_id == session_id,
                Memory.kind == PROVISIONAL_KIND,
                Memory.status == MemoryStatus.PROVISIONAL,
            )
            .order_by(Memory.created_at)
        )
        return [
            ProvisionalMemory(
                m.id,
                str(m.data.get("concept_key")),
                str(m.data.get("dimension")),
                m.data.get("outcome"),
            )
            for m in rows
        ]

    # ── evidence and assessments ──
    async def _concept(self, key: str) -> ConceptInfo:
        info = (await self.catalog()).get(key)
        if info is None:
            raise LookupError(f"concept {key} is not in the active curriculum")
        return info

    async def add_evidence(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewEvidence
    ) -> uuid.UUID:
        concept = await self._concept(item.concept_key)
        inserted = await self.session.scalar(
            pg_insert(EvidenceItem)
            .values(
                user_id=user_id,
                session_id=session_id,
                concept_id=concept.id,
                dimension=item.dimension,
                assistance=item.assistance.value,
                kind=item.kind,
                quote=item.quote,
                transcript_start_s=item.transcript_start_s,
                problem_family=item.problem_family,
                dedupe_key=item.dedupe_key,
                occurred_at=item.occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(EvidenceItem.id)
        )
        if inserted is not None:
            return uuid.UUID(str(inserted))
        existing = await self.session.scalar(
            select(EvidenceItem.id).where(EvidenceItem.dedupe_key == item.dedupe_key)
        )
        assert existing is not None
        return uuid.UUID(str(existing))

    async def save_assessment(
        self, user_id: uuid.UUID, session_id: uuid.UUID, item: NewAssessment
    ) -> SavedAssessment:
        concept = await self._concept(item.concept_key)
        evidence_ids = [await self.add_evidence(user_id, session_id, e) for e in item.evidence]
        previous = list(
            (
                await self.session.scalars(
                    select(Assessment)
                    .where(
                        Assessment.session_id == session_id,
                        Assessment.concept_id == concept.id,
                        Assessment.dimension == item.dimension,
                    )
                    .order_by(Assessment.rev.desc())
                    .with_for_update()
                )
            ).all()
        )
        for p in previous:
            if (
                p.status is not AssessmentStatus.SUPERSEDED
                and p.outcome is item.outcome
                and p.assistance is item.assistance
                and p.judge_model == item.judge_model
                and list(p.evidence_ids) == evidence_ids
            ):
                return await self._saved(p)  # a replayed job: same verdict, not a new revision
        latest = previous[0] if previous else None
        if latest is not None:
            latest.status = AssessmentStatus.SUPERSEDED
        row = Assessment(
            user_id=user_id,
            session_id=session_id,
            concept_id=concept.id,
            dimension=item.dimension,
            rev=(latest.rev + 1) if latest else 1,
            outcome=item.outcome,
            assistance=item.assistance,
            uncertainty=item.uncertainty,
            rationale=item.rationale,
            evidence_ids=evidence_ids,
            judge_model=item.judge_model,
            rubric_id=concept.rubric.id if concept.rubric else None,
            rubric_ver=concept.rubric.version if concept.rubric else None,
            status=item.status,
            supersedes_id=latest.id if latest else None,
        )
        self.session.add(row)
        await self.session.flush()
        return await self._saved(row)

    async def _saved(self, row: Assessment) -> SavedAssessment:
        cited = []
        if row.evidence_ids:
            cited = list(
                (
                    await self.session.execute(
                        select(EvidenceItem.occurred_at, EvidenceItem.problem_family).where(
                            EvidenceItem.id.in_(row.evidence_ids)
                        )
                    )
                ).all()
            )
        return SavedAssessment(
            id=row.id,
            rev=row.rev,
            evidence_ids=tuple(row.evidence_ids),
            occurred_at=max((c.occurred_at for c in cited), default=None),
            problem_family=next((c.problem_family for c in cited if c.problem_family), None),
            supersedes=row.supersedes_id,
        )

    async def set_assessment_status(
        self, assessment_ids: list[uuid.UUID], status: AssessmentStatus
    ) -> None:
        if assessment_ids:
            await self.session.execute(
                update(Assessment).where(Assessment.id.in_(assessment_ids)).values(status=status)
            )

    async def accepted_observations(self, user_id: uuid.UUID) -> list[Observation]:
        rows = (
            await self.session.execute(
                select(Assessment, Concept.key)
                .join(Concept, Concept.id == Assessment.concept_id)
                .where(
                    Assessment.user_id == user_id, Assessment.status == AssessmentStatus.ACCEPTED
                )
            )
        ).all()
        evidence_ids = {i for a, _ in rows for i in a.evidence_ids}
        evidence: dict[uuid.UUID, Any] = {}
        if evidence_ids:
            evidence = {
                e.id: e
                for e in (
                    await self.session.scalars(
                        select(EvidenceItem).where(EvidenceItem.id.in_(evidence_ids))
                    )
                )
            }
        out: list[Observation] = []
        for a, key in rows:
            cited = [evidence[i] for i in a.evidence_ids if i in evidence]
            out.append(
                Observation(
                    assessment_id=a.id,
                    concept_key=key,
                    dimension=a.dimension.value,
                    outcome=AssessmentOutcome(a.outcome),
                    assistance=Assistance(a.assistance),
                    occurred_at=max((e.occurred_at for e in cited), default=a.created_at),
                    evidence_ids=tuple(a.evidence_ids),
                    uncertainty=a.uncertainty,
                    problem_family=next(
                        (e.problem_family for e in cited if e.problem_family), None
                    ),
                )
            )
        return out

    # ── garden ──
    async def garden_state(self, user_id: uuid.UUID) -> GardenSnapshotState:
        plants: dict[str, PlantState] = {}
        rows = await self.session.execute(
            select(PlantRow, Concept.key)
            .join(Concept, Concept.id == PlantRow.concept_id)
            .where(PlantRow.user_id == user_id)
        )
        for row, key in rows.all():
            plants[key] = PlantState.from_row(
                key,
                status=row.status,
                dimension_scores=row.dimension_scores,
                last_evidence_at=row.last_evidence_at,
                next_review_at=row.next_review_at,
            )
        applied = set(
            await self.session.scalars(
                select(func.unnest(GardenRevision.assessment_ids)).where(
                    GardenRevision.user_id == user_id
                )
            )
        )
        rev = await self.session.scalar(
            select(func.coalesce(func.max(GardenRevision.rev), 0)).where(
                GardenRevision.user_id == user_id
            )
        )
        return GardenSnapshotState(GardenState(plants, frozenset(applied)), int(rev or 0))

    async def commit_garden(
        self,
        user_id: uuid.UUID,
        *,
        expected_rev: int,
        result: RulesResult,
        reason: str,
        now: datetime,
    ) -> int:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"garden:{user_id}"},
        )
        current = await self.session.scalar(
            select(func.coalesce(func.max(GardenRevision.rev), 0)).where(
                GardenRevision.user_id == user_id
            )
        )
        if int(current or 0) != expected_rev:
            raise StaleGardenError(f"expected rev {expected_rev}, garden is at {current}")
        catalog = await self.catalog()
        changes = []
        for entry in result.to_revision_changes():
            known = catalog.get(entry["concept"])
            changes.append({**entry, "concept_id": str(known.id)} if known else entry)
        revision = GardenRevision(
            user_id=user_id,
            rev=expected_rev + 1,
            rule_ver=result.rule_version,
            assessment_ids=list(result.assessment_ids),
            reason=reason,
            changes=changes,
        )
        self.session.add(revision)
        await self.session.flush()
        for change in result.changes:
            info = catalog.get(change.concept_key)
            if info is None:
                continue
            after = change.after
            values = {
                "status": after.status,
                "dimension_scores": after.to_scores(),
                "garden_revision_id": revision.id,
                "last_evidence_at": after.last_evidence_at,
                "next_review_at": after.next_review_at,
            }
            await self.session.execute(
                pg_insert(PlantRow)
                .values(user_id=user_id, concept_id=info.id, **values)
                .on_conflict_do_update(index_elements=["user_id", "concept_id"], set_=values)
            )
        return revision.rev

    # ── memory and outbox ──
    async def append_memory(self, new: NewMemory) -> uuid.UUID:
        return (await MemoryStore(self.session).append(new)).id

    async def promote_memory(
        self, memory_id: uuid.UUID, user_id: uuid.UUID, evidence_ids: list[uuid.UUID]
    ) -> None:
        await MemoryStore(self.session).promote(memory_id, user_id, evidence_ids)

    async def dispute_memory(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await MemoryStore(self.session).dispute(memory_id, user_id)

    async def emit(
        self, session_id: uuid.UUID, user_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.session.add(
            SessionEvent(
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                source=EventSource.SERVER,
                payload=payload,
            )
        )
        await self.session.flush()
