"""Seed a demo learner with a believable garden history. Local and dev only.

The history in `script.py` is replayed through the production post-call pipeline, oldest first,
with a clock that matches each conversation, so the garden revisions, plant states, evidence,
assessments and memories are what the real system would have written. Nothing here computes a
score or a plant stage: the deterministic rules engine does, and every growth event cites
evidence the validator verified as a verbatim learner quote.

Idempotent: conversation ids are fixed (`demo_seed_*`), and the pipeline treats a transcript it
has already judged as unchanged. Extra memories are skipped if the same text already exists.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sg_core.demo.script import (
    CONVOS,
    EXTRA_MEMORIES,
    JUDGE_MODEL,
    LEARNER,
    Convo,
    ExtraMemory,
)
from sg_core.evidence import (
    EvidenceStore,
    JudgeRequest,
    PipelineDeps,
    PipelineResult,
    run_post_call,
)
from sg_core.evidence.types import RawVerdict
from sg_core.memory import NewMemory
from sg_core.models.enums import Character, MemoryLayer, MemorySource, MemoryStatus
from sg_core.rules import load_profile
from sg_core.settings import Environment, get_settings

_OBS_OUTCOME = {
    "demonstrated": "correct",
    "partial": "partially_correct",
    "not_demonstrated": "incorrect",
}
_DEMO_CLERK_ID = "user_demo_skillgarden"
_DEMO_EMAIL = "maya.demo@skillgarden.test"


class SeedRefusedError(RuntimeError):
    """The environment is not one the demo seed may write to."""


def guard_environment(*, allow_dev: bool) -> None:
    """Local and test always; dev only with an explicit flag; production never."""
    env = get_settings().environment
    if env is Environment.PROD:
        raise SeedRefusedError("refusing to seed demo data: ENVIRONMENT=prod")
    if env is Environment.DEV and not allow_dev:
        raise SeedRefusedError("ENVIRONMENT=dev: pass --allow-dev to seed the shared dev database")


class ScriptedJudge:
    """Returns the verdicts written in the script. The validator still checks every quote."""

    model = JUDGE_MODEL

    def __init__(self, convos: Sequence[Convo] = CONVOS) -> None:
        self._by_conversation = {c.conversation_id: c for c in convos}

    async def judge(self, request: JudgeRequest) -> list[RawVerdict]:
        convo = self._by_conversation[request.transcript.conversation_id]
        out: list[RawVerdict] = []
        for v in convo.verdicts:
            turn = next(
                (
                    t.index
                    for t in request.transcript.learner_turns()
                    if " ".join(v.quote.lower().split()) in " ".join(t.text.lower().split())
                ),
                -1,
            )
            out.append(
                RawVerdict(
                    concept_key=v.concept,
                    dimension=v.dimension,
                    outcome=v.outcome,
                    assistance=v.assistance,
                    citations=((turn, v.quote),),
                    rationale=v.rationale,
                    uncertainty=v.uncertainty,
                    problem_family=v.family,
                    misconception=v.misconception,
                )
            )
        return out


def conversation_payload(convo: Convo, now: datetime) -> dict[str, Any]:
    """An ElevenLabs-shaped `post_call_transcription` body for one scripted conversation."""
    start = (now - timedelta(days=convo.days_ago)).replace(
        hour=convo.hour_utc, minute=0, second=0, microsecond=0
    )
    step = max(8, convo.duration_s // (len(convo.turns) + 1))
    turns: list[dict[str, Any]] = [
        {
            "role": "user" if t.role == "learner" else "agent",
            "message": t.text,
            "time_in_call_secs": (i + 1) * step,
        }
        for i, t in enumerate(convo.turns)
    ]
    # The agent's own record_observation calls: claims about the learner, never evidence.
    for i, v in enumerate(convo.verdicts):
        params = {
            "concept_id": v.concept,
            "dimension": v.dimension,
            "outcome": _OBS_OUTCOME.get(v.outcome, "no_attempt"),
            "assistance": "hinted" if v.assistance == "assisted" else "independent",
        }
        turns.append(
            {
                "role": "agent",
                "message": "",
                "time_in_call_secs": convo.duration_s - 5,
                "tool_calls": [
                    {
                        "tool_name": "record_observation",
                        "request_id": f"obs_{i}",
                        "params_as_json": json.dumps(params),
                    }
                ],
            }
        )
    return {
        "agent_id": "demo_seed_agent",
        "conversation_id": convo.conversation_id,
        "status": "done",
        "transcript": turns,
        "metadata": {
            "start_time_unix_secs": int(start.timestamp()),
            "call_duration_secs": convo.duration_s,
        },
        "conversation_initiation_client_data": {
            "dynamic_variables": {"focus_concept": convo.focus}
        },
    }


@dataclass(slots=True)
class SeedReport:
    sessions: list[tuple[str, PipelineResult]] = field(default_factory=list)
    memories_added: int = 0

    def lines(self) -> list[str]:
        out = []
        for key, r in self.sessions:
            out.append(
                f"{key:<28} {r.status:<10} rev={r.revision} assessments={r.assessments} "
                f"accepted={r.accepted} reassess={r.reassess} rejected={len(r.rejected)}"
            )
        out.append(f"extra memories added: {self.memories_added}")
        return out


def _profile_normal(_demo: bool) -> Any:
    # History is written with the normal clock even if the account is in DEMO_ACCOUNT_EMAILS.
    return load_profile("normal")


async def replay_history(
    store: EvidenceStore,
    user_id: Any,
    *,
    now: datetime | None = None,
    convos: Sequence[Convo] = CONVOS,
) -> SeedReport:
    """Run every scripted conversation, oldest first, through the production pipeline."""
    now = now or datetime.now(UTC)
    report = SeedReport()
    judge = ScriptedJudge(convos)
    for convo in sorted(convos, key=lambda c: -c.days_ago):
        payload = conversation_payload(convo, now)
        started = datetime.fromtimestamp(payload["metadata"]["start_time_unix_secs"], UTC)
        await store.ensure_session(
            user_id=user_id,
            character=Character(convo.character),
            mode=convo.mode,
            conversation_id=convo.conversation_id,
            public_session_id=None,
            now=started,
        )
        finished = started + timedelta(seconds=convo.duration_s + 60)
        deps = PipelineDeps(
            store=store, judge=judge, profile_for=_profile_normal, clock=_fixed(finished)
        )
        report.sessions.append((convo.key, await run_post_call(deps, payload)))
    return report


def _fixed(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


async def add_extra_memories(
    append: Callable[[NewMemory], Any],
    existing: set[str],
    user_id: Any,
    extras: Sequence[ExtraMemory] = EXTRA_MEMORIES,
) -> int:
    added = 0
    for m in extras:
        if m.content in existing:
            continue
        await append(
            NewMemory(
                user_id=user_id,
                layer=MemoryLayer(m.layer),
                kind=m.kind,
                content=m.content,
                source=MemorySource(m.source),
                source_character=Character(m.character) if m.character else None,
                status=MemoryStatus.ACCEPTED,
                data={"seed": "demo-history@1"},
            )
        )
        added += 1
    return added


async def seed_database(
    *,
    clerk_user_id: str | None = None,
    email: str | None = None,
    allow_dev: bool = False,
    now: datetime | None = None,
) -> tuple[SeedReport, str]:
    """Create or update the demo user, then replay the history into the configured database."""
    from sqlalchemy import select

    from sg_core.curriculum import curriculum_path, load_curriculum, sync_curriculum
    from sg_core.db import get_engine, get_sessionmaker
    from sg_core.memory import MemoryStore
    from sg_core.models.curriculum import Curriculum
    from sg_core.models.enums import CurriculumStatus
    from sg_core.models.identity import Profile, User
    from sg_core.models.memory import Memory

    guard_environment(allow_dev=allow_dev)
    clerk_user_id = clerk_user_id or _DEMO_CLERK_ID
    email = (email or _DEMO_EMAIL).lower()
    now = now or datetime.now(UTC)
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            active = await session.scalar(
                select(Curriculum.id).where(Curriculum.status == CurriculumStatus.ACTIVE).limit(1)
            )
            if active is None:  # a fresh database: load and activate cs-core@v1
                spec = load_curriculum(curriculum_path("cs-core", "v1"))
                await sync_curriculum(session, spec, activate=True)

            user = await session.scalar(select(User).where(User.clerk_user_id == clerk_user_id))
            if user is None:
                user = User(
                    clerk_user_id=clerk_user_id,
                    email=email,
                    display_name=LEARNER["display_name"],
                    timezone=LEARNER["timezone"],
                )
                session.add(user)
                await session.flush()
            profile = await session.get(Profile, user.id)
            if profile is None:
                session.add(
                    Profile(
                        user_id=user.id,
                        major=LEARNER["major"],
                        experience_level=LEARNER["experience_level"],
                        target_role=LEARNER["target_role"],
                        goals=list(LEARNER["goals"]),
                        onboarded_at=now - timedelta(days=63),
                    )
                )
            user_id = user.id

        # One transaction per conversation: a failure keeps what was already written, and a
        # re-run resumes (judged conversations come back as "unchanged").
        report = SeedReport()
        async with sessionmaker() as session:
            report.sessions = await _replay_each(session, user_id, now)

        async with sessionmaker() as session, session.begin():
            existing = set(
                (
                    await session.scalars(
                        select(Memory.content).where(
                            Memory.user_id == user_id,
                            Memory.kind.in_({m.kind for m in EXTRA_MEMORIES}),
                        )
                    )
                ).all()
            )
            store = MemoryStore(session)

            async def _append(new: NewMemory) -> Any:
                return await store.append(new)

            report.memories_added = await add_extra_memories(_append, existing, user_id)
    finally:
        await get_engine().dispose()
    return report, clerk_user_id


async def _replay_each(
    session: Any, user_id: Any, now: datetime
) -> list[tuple[str, PipelineResult]]:
    from sg_core.evidence.db_store import DbEvidenceStore

    out: list[tuple[str, PipelineResult]] = []
    for convo in sorted(CONVOS, key=lambda c: -c.days_ago):
        async with session.begin():
            store = DbEvidenceStore(session)
            report = await replay_history(store, user_id, now=now, convos=(convo,))
            out.extend(report.sessions)
    return out
