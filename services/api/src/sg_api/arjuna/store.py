"""Storage for Arjuna: code snapshots, sandbox runs, hints, test evidence and the plan inputs.

Every method is scoped to the owner of the session: callers resolve a `SessionCtx` from the
Clerk user ID and the session ID (a session of another learner, or another character, resolves
to None) and everything else hangs off that context.

Evidence rules honoured here:
- A tests run is stored as `evidence_items` (`kind=code_run`) linked to the exact code snapshot
  and sandbox run, so a claim of growth can cite the code and the result.
- If Arjuna gave any hint on the problem, that evidence is `assisted`; otherwise `independent`.
  Assisted evidence is never relabelled afterwards.
- Visible-example runs ("Run examples" in the editor) are practice: no evidence row.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sg_api.arjuna.plan import MAX_TEXT_CHARS
from sg_api.arjuna.problems import Problem
from sg_api.arjuna.runner import TestReport
from sg_api.drona.store import active_curriculum_id, parse_uuid
from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.models.curriculum import Concept
from sg_core.models.enums import (
    Assistance,
    Character,
    Dimension,
    DocumentKind,
    EventSource,
    SandboxRunStatus,
)
from sg_core.models.evidence import EvidenceItem
from sg_core.models.identity import User
from sg_core.models.knowledge import Chunk, Document
from sg_core.models.sessions import CodeSnapshot, HintGiven, SandboxRun, SessionEvent
from sg_core.models.sessions import Session as SessionRow

log = get_logger(__name__)

MAX_SNAPSHOT_CHARS = 50_000
RUN_KINDS = ("tests", "examples")


@dataclass(frozen=True)
class SessionCtx:
    user_id: uuid.UUID
    session_id: uuid.UUID
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    id: uuid.UUID
    problem_id: str
    language: str
    code: str
    content_hash: str
    captured_at: datetime


@dataclass(frozen=True)
class SnapshotRef:
    id: uuid.UUID
    duplicate: bool


@dataclass(frozen=True)
class RunRecord:
    id: uuid.UUID
    problem_id: str
    kind: str  # tests | examples
    status: str
    passed: int
    total: int
    summary: str
    first_failure: str | None
    at: datetime
    assisted: bool = False


@dataclass(frozen=True)
class PlanSources:
    resume_text: str | None
    job_description_text: str | None
    concept_keys: frozenset[str]


class ArjunaStore(Protocol):
    async def resolve(self, clerk_user_id: str, session_id: str) -> SessionCtx | None:
        """The learner's own Arjuna session, or None."""

    async def plan_sources(self, clerk_user_id: str) -> PlanSources: ...

    async def set_attributes(self, ctx: SessionCtx, attributes: dict[str, Any]) -> None: ...

    async def save_snapshot(
        self, ctx: SessionCtx, *, problem_id: str, language: str, code: str, trigger: str
    ) -> SnapshotRef: ...

    async def latest_snapshot(self, ctx: SessionCtx, problem_id: str) -> Snapshot | None: ...

    async def hint_levels(self, ctx: SessionCtx, problem_id: str) -> list[int]: ...

    async def record_hint(
        self, ctx: SessionCtx, problem: Problem, *, level: int, content: str
    ) -> None: ...

    async def count_runs(self, ctx: SessionCtx, kind: str) -> int: ...

    async def record_run(
        self,
        ctx: SessionCtx,
        *,
        problem: Problem,
        snapshot: Snapshot,
        report: TestReport,
        kind: str,
        assisted: bool,
        now: datetime,
    ) -> RunRecord: ...

    async def list_runs(
        self, ctx: SessionCtx, *, after: datetime | None, kind: str = "tests"
    ) -> list[RunRecord]: ...


def content_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def run_status(report: TestReport) -> SandboxRunStatus:
    return {
        "passed": SandboxRunStatus.PASSED,
        "failed": SandboxRunStatus.FAILED,
        "timeout": SandboxRunStatus.TIMEOUT,
    }.get(report.status, SandboxRunStatus.ERROR)


def evidence_quote(problem: Problem, snapshot: Snapshot, report: TestReport, assisted: bool) -> str:
    base = (
        f"Ran the hidden tests for {problem.title} on their {snapshot.language} code: "
        f"{report.passed} of {report.total} passed"
    )
    return base + (" after a hint." if assisted else " with no hints.")


# ── Postgres ──────────────────────────────────────────────────────────────────────────────────


class DbArjunaStore:
    async def _user_id(self, db: AsyncSession, clerk_user_id: str) -> uuid.UUID | None:
        return await db.scalar(
            select(User.id).where(User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None))
        )

    async def resolve(self, clerk_user_id: str, session_id: str) -> SessionCtx | None:
        sid = parse_uuid(session_id)
        if sid is None:
            return None
        async with get_sessionmaker()() as db:
            user_id = await self._user_id(db, clerk_user_id)
            if user_id is None:
                return None
            row = await db.scalar(
                select(SessionRow).where(
                    SessionRow.id == sid,
                    SessionRow.user_id == user_id,
                    SessionRow.character == Character.ARJUNA,
                )
            )
            if row is None:
                return None
            return SessionCtx(user_id, row.id, dict(row.attributes or {}))

    async def plan_sources(self, clerk_user_id: str) -> PlanSources:
        async with get_sessionmaker()() as db:
            user_id = await self._user_id(db, clerk_user_id)
            curriculum_id = await active_curriculum_id(db)
            keys: frozenset[str] = frozenset()
            if curriculum_id is not None:
                keys = frozenset(
                    await db.scalars(
                        select(Concept.key).where(Concept.curriculum_id == curriculum_id)
                    )
                )
            if user_id is None:
                return PlanSources(None, None, keys)
            texts: dict[DocumentKind, str | None] = {}
            for kind in (DocumentKind.RESUME, DocumentKind.JOB_DESCRIPTION):
                version_id = await db.scalar(
                    select(Document.active_version_id)
                    .where(
                        Document.user_id == user_id,
                        Document.kind == kind,
                        Document.deleted_at.is_(None),
                        Document.active_version_id.is_not(None),
                    )
                    .order_by(Document.created_at.desc())
                    .limit(1)
                )
                if version_id is None:
                    texts[kind] = None
                    continue
                parts = await db.scalars(
                    select(Chunk.content)
                    .where(Chunk.document_version_id == version_id, Chunk.user_id == user_id)
                    .order_by(Chunk.ordinal)
                )
                # Chunks overlap; for keyword counting that only inflates counts slightly, and
                # for project lines duplicates are dropped.
                texts[kind] = "\n".join(parts)[:MAX_TEXT_CHARS] or None
            return PlanSources(
                texts[DocumentKind.RESUME], texts[DocumentKind.JOB_DESCRIPTION], keys
            )

    async def set_attributes(self, ctx: SessionCtx, attributes: dict[str, Any]) -> None:
        async with get_sessionmaker()() as db:
            row = await db.get(SessionRow, ctx.session_id, with_for_update=True)
            if row is not None:
                row.attributes = {**(row.attributes or {}), **attributes}
                await db.commit()

    async def save_snapshot(
        self, ctx: SessionCtx, *, problem_id: str, language: str, code: str, trigger: str
    ) -> SnapshotRef:
        digest = content_hash(code)
        async with get_sessionmaker()() as db:
            latest = await db.execute(
                select(CodeSnapshot.id, CodeSnapshot.content_hash, CodeSnapshot.language)
                .where(
                    CodeSnapshot.session_id == ctx.session_id,
                    CodeSnapshot.problem_ref == problem_id,
                )
                .order_by(CodeSnapshot.captured_at.desc())
                .limit(1)
            )
            last = latest.first()
            if last is not None and last.content_hash == digest and last.language == language:
                return SnapshotRef(last.id, True)
            row = CodeSnapshot(
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                problem_ref=problem_id,
                language=language,
                code=code,
                content_hash=digest,
                trigger=trigger,
            )
            db.add(row)
            await db.commit()
            return SnapshotRef(row.id, False)

    async def latest_snapshot(self, ctx: SessionCtx, problem_id: str) -> Snapshot | None:
        async with get_sessionmaker()() as db:
            row = await db.scalar(
                select(CodeSnapshot)
                .where(
                    CodeSnapshot.session_id == ctx.session_id,
                    CodeSnapshot.problem_ref == problem_id,
                )
                .order_by(CodeSnapshot.captured_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            return Snapshot(
                row.id, problem_id, row.language, row.code, row.content_hash, row.captured_at
            )

    async def hint_levels(self, ctx: SessionCtx, problem_id: str) -> list[int]:
        async with get_sessionmaker()() as db:
            return [
                int(v)
                for v in await db.scalars(
                    select(HintGiven.level)
                    .where(
                        HintGiven.session_id == ctx.session_id, HintGiven.question_ref == problem_id
                    )
                    .order_by(HintGiven.given_at)
                )
            ]

    async def record_hint(
        self, ctx: SessionCtx, problem: Problem, *, level: int, content: str
    ) -> None:
        async with get_sessionmaker()() as db:
            curriculum_id = await active_curriculum_id(db)
            concept_id = None
            if curriculum_id is not None:
                concept_id = await db.scalar(
                    select(Concept.id).where(
                        Concept.curriculum_id == curriculum_id, Concept.key == problem.concept_key
                    )
                )
            db.add(
                HintGiven(
                    session_id=ctx.session_id,
                    user_id=ctx.user_id,
                    concept_id=concept_id,
                    question_ref=problem.id,
                    level=level,
                    content=content,
                )
            )
            await db.commit()

    async def count_runs(self, ctx: SessionCtx, kind: str) -> int:
        async with get_sessionmaker()() as db:
            total = await db.scalar(
                select(func.count())
                .select_from(SandboxRun)
                .where(
                    SandboxRun.session_id == ctx.session_id,
                    SandboxRun.result["kind"].astext == kind,
                )
            )
            return int(total or 0)

    async def record_run(
        self,
        ctx: SessionCtx,
        *,
        problem: Problem,
        snapshot: Snapshot,
        report: TestReport,
        kind: str,
        assisted: bool,
        now: datetime,
    ) -> RunRecord:
        first = report.first_failure
        async with get_sessionmaker()() as db:
            run = SandboxRun(
                session_id=ctx.session_id,
                code_snapshot_id=snapshot.id,
                user_id=ctx.user_id,
                status=run_status(report),
                tests_passed=report.passed,
                tests_total=report.total,
                duration_ms=report.duration_ms,
                finished_at=now,
                result={
                    "kind": kind,
                    "problem_id": problem.id,
                    "language": snapshot.language,
                    "summary": report.summary,
                    "first_failure": first.label if first else None,
                    "assisted": assisted,
                },
            )
            db.add(run)
            await db.flush()
            if kind == "tests":
                concept_id = None
                curriculum_id = await active_curriculum_id(db)
                if curriculum_id is not None:
                    concept_id = await db.scalar(
                        select(Concept.id).where(
                            Concept.curriculum_id == curriculum_id,
                            Concept.key == problem.concept_key,
                        )
                    )
                if concept_id is not None:
                    hint_ids = list(
                        await db.scalars(
                            select(HintGiven.id).where(
                                HintGiven.session_id == ctx.session_id,
                                HintGiven.question_ref == problem.id,
                            )
                        )
                    )
                    await db.execute(
                        pg_insert(EvidenceItem)
                        .values(
                            user_id=ctx.user_id,
                            session_id=ctx.session_id,
                            concept_id=concept_id,
                            dimension=Dimension.APPLICATION.value,
                            assistance=(
                                Assistance.ASSISTED if assisted else Assistance.INDEPENDENT
                            ).value,
                            kind="code_run",
                            quote=evidence_quote(problem, snapshot, report, assisted),
                            code_snapshot_id=snapshot.id,
                            sandbox_run_id=run.id,
                            hint_ids=hint_ids,
                            problem_family=problem.family,
                            dedupe_key=f"code_run:{run.id}",
                            occurred_at=now,
                        )
                        .on_conflict_do_nothing(index_elements=["dedupe_key"])
                    )
                await db.execute(
                    pg_insert(SessionEvent).values(
                        session_id=ctx.session_id,
                        user_id=ctx.user_id,
                        event_type="arjuna.tests_run",
                        source=EventSource.SERVER.value,
                        payload={
                            "run_id": str(run.id),
                            "problem_id": problem.id,
                            "status": report.status,
                            "passed": report.passed,
                            "total": report.total,
                            "assisted": assisted,
                        },
                    )
                )
            await db.commit()
            return _record(run)

    async def list_runs(
        self, ctx: SessionCtx, *, after: datetime | None, kind: str = "tests"
    ) -> list[RunRecord]:
        async with get_sessionmaker()() as db:
            query = (
                select(SandboxRun)
                .where(
                    SandboxRun.session_id == ctx.session_id,
                    SandboxRun.result["kind"].astext == kind,
                )
                .order_by(SandboxRun.created_at)
                .limit(50)
            )
            if after is not None:
                query = query.where(SandboxRun.created_at > after)
            return [_record(r) for r in await db.scalars(query)]


def _record(run: SandboxRun) -> RunRecord:
    result = run.result or {}
    return RunRecord(
        id=run.id,
        problem_id=str(result.get("problem_id", "")),
        kind=str(result.get("kind", "tests")),
        status=run.status.value,
        passed=run.tests_passed or 0,
        total=run.tests_total or 0,
        summary=str(result.get("summary", "")),
        first_failure=result.get("first_failure"),
        at=run.finished_at or run.created_at,
        assisted=bool(result.get("assisted", False)),
    )


# ── In memory (tests and local runs without a database) ───────────────────────────────────────


@dataclass
class InMemoryArjunaStore:
    sources: PlanSources = field(
        default_factory=lambda: PlanSources(None, None, frozenset({"dsa.hash_tables"}))
    )
    owner: str = "user_clerk_1"
    sessions: dict[str, SessionCtx] = field(default_factory=dict)
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    snapshots: list[Snapshot] = field(default_factory=list)
    hints: list[tuple[str, str, int, str]] = field(
        default_factory=list
    )  # session, problem, lvl, text
    runs: list[tuple[uuid.UUID, RunRecord]] = field(default_factory=list)  # session id, run
    evidence: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def add_session(self, session_id: uuid.UUID, *, user: str | None = None) -> SessionCtx:
        ctx = SessionCtx(uuid.uuid4(), session_id, {})
        self.sessions[f"{user or self.owner}:{session_id}"] = ctx
        return ctx

    async def resolve(self, clerk_user_id: str, session_id: str) -> SessionCtx | None:
        return self.sessions.get(f"{clerk_user_id}:{session_id}")

    async def plan_sources(self, clerk_user_id: str) -> PlanSources:
        return self.sources

    async def set_attributes(self, ctx: SessionCtx, attributes: dict[str, Any]) -> None:
        self.attributes.setdefault(str(ctx.session_id), {}).update(attributes)

    async def save_snapshot(
        self, ctx: SessionCtx, *, problem_id: str, language: str, code: str, trigger: str
    ) -> SnapshotRef:
        digest = content_hash(code)
        mine = [s for s in self.snapshots if s.problem_id == problem_id]
        if mine and mine[-1].content_hash == digest and mine[-1].language == language:
            return SnapshotRef(mine[-1].id, True)
        snap = Snapshot(uuid.uuid4(), problem_id, language, code, digest, datetime.now(UTC))
        self.snapshots.append(snap)
        return SnapshotRef(snap.id, False)

    async def latest_snapshot(self, ctx: SessionCtx, problem_id: str) -> Snapshot | None:
        mine = [s for s in self.snapshots if s.problem_id == problem_id]
        return mine[-1] if mine else None

    async def hint_levels(self, ctx: SessionCtx, problem_id: str) -> list[int]:
        return [lvl for s, p, lvl, _ in self.hints if s == str(ctx.session_id) and p == problem_id]

    async def record_hint(
        self, ctx: SessionCtx, problem: Problem, *, level: int, content: str
    ) -> None:
        self.hints.append((str(ctx.session_id), problem.id, level, content))

    async def count_runs(self, ctx: SessionCtx, kind: str) -> int:
        return sum(1 for s, r in self.runs if s == ctx.session_id and r.kind == kind)

    async def record_run(
        self,
        ctx: SessionCtx,
        *,
        problem: Problem,
        snapshot: Snapshot,
        report: TestReport,
        kind: str,
        assisted: bool,
        now: datetime,
    ) -> RunRecord:
        first = report.first_failure
        record = RunRecord(
            uuid.uuid4(),
            problem.id,
            kind,
            run_status(report).value,
            report.passed,
            report.total,
            report.summary,
            first.label if first else None,
            now,
            assisted,
        )
        self.runs.append((ctx.session_id, record))
        if kind == "tests":
            self.evidence.append(
                {
                    "concept": problem.concept_key,
                    "dimension": "application",
                    "assistance": "assisted" if assisted else "independent",
                    "kind": "code_run",
                    "quote": evidence_quote(problem, snapshot, report, assisted),
                    "snapshot_id": snapshot.id,
                    "run_id": record.id,
                    "family": problem.family,
                }
            )
            self.events.append({"type": "arjuna.tests_run", "run_id": record.id})
        return record

    async def list_runs(
        self, ctx: SessionCtx, *, after: datetime | None, kind: str = "tests"
    ) -> list[RunRecord]:
        return [
            r
            for s, r in self.runs
            if s == ctx.session_id and r.kind == kind and (after is None or r.at > after)
        ]


_store: ArjunaStore | None = None


def get_arjuna_store() -> ArjunaStore:
    global _store
    if _store is None:
        _store = DbArjunaStore()
    return _store
