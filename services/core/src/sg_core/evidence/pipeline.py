"""The post-call evidence pipeline: transcript -> judge -> validation -> rules -> garden revision.

    run_post_call(deps, data) -> PipelineResult

1. Normalise the transcript (webhook body, or fetched from ElevenLabs when the body lacks one).
2. Find the session by conversation id; work out which concepts could have been assessed.
3. One judge pass (bounded sections for long sessions) returns structured verdicts.
4. `validate_verdicts` checks schema, ownership and that every citation is the learner's own
   verbatim words; assistance can only be raised, never lowered, by what is on record.
5. Evidence items and assessment revisions are stored; re-judging adds a revision.
6. The deterministic rules engine alone turns accepted assessments into a garden revision. This
   module never computes a score or a plant stage.
7. Provisional growth the live micro-judge showed is confirmed (promoted) or retracted with an
   explanation, and an outbox event announces the revision.

Everything runs in the caller's transaction (the provider-event handler's savepoint), so a failure
leaves no half-written garden and the job system can retry.
"""

import dataclasses
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sg_core.economics.usage import UsageContext
from sg_core.evidence.code_runs import CODE_RUN_JUDGE, code_digest, code_run_verdicts
from sg_core.evidence.judge import Judge, JudgeRequest
from sg_core.evidence.store import (
    EvidenceStore,
    NewAssessment,
    NewEvidence,
    ProvisionalMemory,
    SavedAssessment,
    SessionRef,
    StaleGardenError,
)
from sg_core.evidence.transcript import (
    normalize,
    observations_in,
    occurred_at,
    parse_conversation,
    transcript_hash,
)
from sg_core.evidence.types import (
    AgentObservation,
    CodeRun,
    ConceptInfo,
    PipelineResult,
    Rejection,
    Transcript,
    Verdict,
)
from sg_core.evidence.validation import ValidationContext, validate_verdicts
from sg_core.logging import get_logger
from sg_core.memory import NewMemory
from sg_core.models.enums import (
    AssessmentOutcome,
    AssessmentStatus,
    Character,
    CostCenter,
    MemoryLayer,
    MemorySource,
    MemoryStatus,
    PlantStatus,
    SessionStatus,
)
from sg_core.providers.elevenlabs import ConversationDetails
from sg_core.rules import (
    GardenState,
    Observation,
    PlantChange,
    PlantState,
    RulesProfile,
    RulesResult,
    profile_for_account,
    propose,
    replay,
)

log = get_logger(__name__)

MAX_COMMIT_ATTEMPTS = 4
MAX_CANDIDATES = 12
_RESULT_OUTCOMES = (AssessmentOutcome.DEMONSTRATED, AssessmentOutcome.PARTIAL)


class SessionNotFoundError(LookupError):
    """No session is bound to this conversation yet. Raised so the event is retried."""


class ConversationSource(Protocol):
    async def get_conversation(self, conversation_id: str) -> ConversationDetails: ...


def _default_profile(demo: bool) -> RulesProfile:
    return profile_for_account(demo=demo)


@dataclasses.dataclass(slots=True)
class PipelineDeps:
    store: EvidenceStore
    judge: Judge
    conversations: ConversationSource | None = None
    profile_for: Callable[[bool], RulesProfile] = _default_profile
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


async def run_post_call(deps: PipelineDeps, data: Mapping[str, Any]) -> PipelineResult:
    """Run the pipeline for one `post_call_transcription` body (`data` is the webhook's `data`)."""
    store = deps.store
    now = deps.clock()
    conversation_id = str(data.get("conversation_id") or "")
    if not conversation_id:
        raise ValueError("post-call payload has no conversation_id")

    transcript = parse_conversation(data, conversation_id=conversation_id)
    if not transcript.turns and deps.conversations is not None:
        # Reconcile through the provider API when the webhook carried no usable transcript.
        details = await deps.conversations.get_conversation(conversation_id)
        transcript = parse_conversation(details.raw, conversation_id=conversation_id)

    session = await store.find_session(conversation_id)
    if session is None:
        raise SessionNotFoundError(f"no session is bound to conversation {conversation_id}")

    digest = transcript_hash(transcript)
    # Arjuna's stored hidden-tests runs are evidence too: read them whatever the transcript says.
    code_runs = await store.code_runs(session.id)
    code_fingerprint = code_digest(code_runs)
    done = session.attributes.get("post_call") or {}
    if (
        done.get("transcript_hash") == digest
        and done.get("code_digest", "") == code_fingerprint
        and done.get("judged")
    ):
        return PipelineResult(status="unchanged", session_id=session.id)

    ended_at = (
        transcript.started_at.replace(microsecond=0) + timedelta(seconds=transcript.duration_s)
        if transcript.started_at and transcript.duration_s is not None
        else now
    )
    await store.patch_session(
        session.id,
        status=SessionStatus.COMPLETED
        if transcript.status in (None, "done")
        else SessionStatus.INTERRUPTED,
        started_at=transcript.started_at,
        ended_at=ended_at,
        duration_seconds=int(transcript.duration_s) if transcript.duration_s is not None else None,
    )

    catalog = await store.catalog()
    code_verdicts = code_run_verdicts(code_runs, catalog)
    code_concepts = {v.concept_key for v in code_verdicts}
    extra = {"code_digest": code_fingerprint}
    retention_concept: str | None = None
    if session.character == Character.BHIMA.value:
        retention_concept = await store.retention_concept(session.user_id, conversation_id)

    if not transcript.learner_turns() and not code_verdicts:
        await _finish(store, session, digest, "empty_transcript", extra, now)
        await _retention_result(store, session, retention_concept, None, set(), None)
        return PipelineResult(status="empty_transcript", session_id=session.id)

    observations = observations_in(transcript)
    provisional = await store.provisional_memories(session.id)
    candidates = (
        _candidates(session, transcript, observations, provisional, retention_concept, catalog)
        if transcript.learner_turns()
        else set()
    )
    if not candidates and not code_verdicts:
        await _finish(store, session, digest, "no_candidates", extra, now)
        await _retention_result(store, session, retention_concept, None, set(), None)
        return PipelineResult(status="no_candidates", session_id=session.id)

    verdicts: list[Verdict] = []
    rejected: list[Rejection] = []
    if candidates:
        raw = await deps.judge.judge(
            JudgeRequest(
                transcript=transcript,
                concepts=[catalog[k] for k in sorted(candidates)],
                usage=UsageContext(
                    cost_center=CostCenter.LEARNER,
                    component="evidence.judge",
                    user_id=session.user_id,
                    session_id=session.id,
                    idempotency_key=None,
                ),
                key_prefix=f"judge:{conversation_id}:{digest}",
                dimension_rubrics=await store.dimension_rubrics(),
            )
        )
        verdicts, rejected = validate_verdicts(
            raw,
            ValidationContext(
                transcript=transcript,
                catalog=catalog,
                candidates=candidates,
                character=session.character,
                observations=observations,
                hinted_concepts=await store.hinted_concepts(session.id),
                retention_concept=retention_concept,
                code_run_concepts=code_concepts,
            ),
        )

    result = PipelineResult(status="judged", session_id=session.id, rejected=list(rejected))
    saved = await _save(deps, session, transcript, [*verdicts, *code_verdicts], catalog, now)
    result.assessments = len(saved)

    garden, rev = await _apply_rules(deps, session, saved, catalog, now)
    result.revision = rev
    reassess = set(garden.reassess) if garden else set()
    result.reassess = len(reassess)
    grew = _grew(garden)
    if reassess:
        await store.set_assessment_status(sorted(reassess), AssessmentStatus.PENDING)
    result.accepted = sum(1 for _, s in saved if s.id not in reassess)

    result.confirmed, result.retracted = await _reconcile_provisional(
        store, session, provisional, saved, grew, garden
    )
    await _write_memories(store, session, saved, catalog, grew, reassess)
    await _retention_result(store, session, retention_concept, saved, grew, garden)

    changed = sorted({c.concept_key for c in garden.changes}) if garden else []
    if rev is not None:
        await store.emit(
            session.id,
            session.user_id,
            "garden.revision",
            {"rev": rev, "concepts": changed, "reason": "assessment"},
        )
    await _finish(
        store,
        session,
        digest,
        "judged",
        {
            "revision": rev,
            "assessments": result.assessments,
            "rejected": [dataclasses.asdict(r) for r in rejected][:20],
            "judge_model": deps.judge.model,
            "code_runs": len(code_runs),
            "confirmed": result.confirmed,
            "retracted": result.retracted,
            **extra,
        },
        now,
    )
    return result


def _candidates(
    session: SessionRef,
    transcript: Transcript,
    observations: list[AgentObservation],
    provisional: list[ProvisionalMemory],
    retention_concept: str | None,
    catalog: Mapping[str, ConceptInfo],
) -> set[str]:
    if session.character == Character.BHIMA.value:
        # Bhima's call produces at most one piece of technical evidence: the retention answer.
        if retention_concept is not None and retention_concept in catalog:
            return {retention_concept}
        return set()
    keys = {o.concept_key for o in observations} | {p.concept_key for p in provisional}
    focus = transcript.dynamic_variables.get("focus_concept")
    if focus:
        keys.add(focus)
    return set(sorted(k for k in keys if k in catalog)[:MAX_CANDIDATES])


async def _save(
    deps: PipelineDeps,
    session: SessionRef,
    transcript: Transcript,
    verdicts: list[Verdict],
    catalog: Mapping[str, ConceptInfo],
    now: datetime,
) -> list[tuple[Verdict, SavedAssessment]]:
    saved: list[tuple[Verdict, SavedAssessment]] = []
    fallback = transcript.started_at or now
    for v in verdicts:
        if v.code_run is not None:
            saved.append((v, await _save_code_run(deps, session, v, v.code_run)))
            continue
        evidence = tuple(
            NewEvidence(
                concept_key=v.concept_key,
                dimension=v.dimension,
                assistance=v.assistance,
                kind="teach_back"
                if session.mode == "teach_back" and v.dimension == "explanation"
                else "quote",
                quote=c.quote,
                occurred_at=occurred_at(transcript, c.turn, fallback),
                dedupe_key=_dedupe(transcript.conversation_id, c.turn, v, c.quote),
                transcript_start_s=(t.time_s if (t := transcript.turn(c.turn)) else None),
                problem_family=v.problem_family,
            )
            for c in v.citations
        )
        item = NewAssessment(
            concept_key=v.concept_key,
            dimension=v.dimension,
            outcome=v.outcome,
            assistance=v.assistance,
            uncertainty=v.uncertainty,
            rationale=v.rationale,
            judge_model=deps.judge.model,
            evidence=evidence,
        )
        saved.append((v, await deps.store.save_assessment(session.user_id, session.id, item)))
    return saved


async def _save_code_run(
    deps: PipelineDeps, session: SessionRef, v: Verdict, run: CodeRun
) -> SavedAssessment:
    """Assess a stored code run. Its evidence row exists already; the dedupe key makes the
    store return that row, so the assessment cites the real code snapshot and sandbox run."""
    item = NewAssessment(
        concept_key=v.concept_key,
        dimension=v.dimension,
        outcome=v.outcome,
        assistance=v.assistance,
        uncertainty=v.uncertainty,
        rationale=v.rationale,
        judge_model=CODE_RUN_JUDGE,
        evidence=(
            NewEvidence(
                concept_key=v.concept_key,
                dimension=v.dimension,
                assistance=v.assistance,
                kind="code_run",
                quote=run.quote,
                occurred_at=run.occurred_at,
                dedupe_key=run.dedupe_key,
                problem_family=run.problem_family,
            ),
        ),
    )
    return await deps.store.save_assessment(session.user_id, session.id, item)


async def _retention_result(
    store: EvidenceStore,
    session: SessionRef,
    retention_concept: str | None,
    saved: list[tuple[Verdict, SavedAssessment]] | None,
    grew: set[Any],
    garden: RulesResult | None,
) -> None:
    """Close the loop on a Bhima retention question: record what became of the answer.

    The answer itself is evidence only through the judge and the rules engine (above). This
    writes a `retention_result` session memory so the learner's history and the next briefing
    know whether the question was answered, how it was judged and whether it counted, and emits
    `bhima.retention_judged`. It never changes the garden. A habit report is not an answer.
    """
    if session.character != Character.BHIMA.value or retention_concept is None:
        return
    pair = next(
        (
            (v, s)
            for v, s in (saved or [])
            if v.concept_key == retention_concept and v.dimension == "retention"
        ),
        None,
    )
    title = retention_concept
    data: dict[str, Any] = {
        "concept_key": retention_concept,
        "source": "retention_call",
        "conversation_id": session.conversation_id,
    }
    evidence_ids: list[Any] = []
    if pair is None:
        data.update(answered=False, outcome="no_answer", counted=False)
        content = f"Bhima asked about {title}; there was no usable answer, so nothing changed."
    else:
        v, s = pair
        counted = s.id in grew
        skipped = {sk.assessment_id: sk.reason for sk in garden.skipped} if garden else {}
        data.update(
            answered=True,
            outcome=v.outcome.value,
            assistance=v.assistance.value,
            counted=counted,
            assessment_id=str(s.id),
            skip_reason=None if counted else skipped.get(s.id),
        )
        evidence_ids = list(s.evidence_ids)
        content = (
            f"Bhima asked about {title}; the answer was judged {v.outcome.value} "
            f"({v.assistance.value}) and {'counted toward' if counted else 'did not change'} "
            "the garden."
        )
    await store.append_memory(
        NewMemory(
            user_id=session.user_id,
            layer=MemoryLayer.SESSION,
            kind="retention_result",
            content=content,
            source=MemorySource.EVIDENCE_PIPELINE,
            source_character=Character.BHIMA,
            source_session_id=session.id,
            evidence_ids=evidence_ids,
            status=MemoryStatus.ACCEPTED,
            data=data,
        )
    )
    await store.emit(session.id, session.user_id, "bhima.retention_judged", data)


def _dedupe(conversation_id: str, turn: int, v: Verdict, quote: str) -> str:
    digest = hashlib.sha256(normalize(quote).encode()).hexdigest()[:10]
    return f"pc:{conversation_id}:{turn}:{v.concept_key}:{v.dimension}:{digest}"[:256]


async def _apply_rules(
    deps: PipelineDeps,
    session: SessionRef,
    saved: list[tuple[Verdict, SavedAssessment]],
    catalog: Mapping[str, ConceptInfo],
    now: datetime,
) -> tuple[RulesResult | None, int | None]:
    store = deps.store
    if not saved:
        return None, None
    profile = deps.profile_for(await store.is_demo_account(session.user_id))
    observations = [
        Observation(
            assessment_id=s.id,
            concept_key=v.concept_key,
            dimension=v.dimension,
            outcome=v.outcome,
            assistance=v.assistance,
            occurred_at=s.occurred_at or now,
            evidence_ids=s.evidence_ids,
            uncertainty=v.uncertainty,
            problem_family=s.problem_family,
        )
        for v, s in saved
    ]
    rejudged = any(s.supersedes is not None for _, s in saved)
    known = set(catalog)
    result: RulesResult | None = None
    for _ in range(MAX_COMMIT_ATTEMPTS):
        snap = await store.garden_state(session.user_id)
        result = propose(snap.state, observations, now, profile, known_concepts=known)
        reason = "assessment"
        if rejudged or any(sk.reason == "out_of_order" for sk in result.skipped):
            # Evidence older than the plant's newest, or an assessment that replaced an earlier
            # one: never patch incrementally. Rebuild from every accepted assessment.
            result = await _rebuild(store, session, snap.state, result, profile, now, known)
            reason = "correction"
        if not result.changes:
            return result, None
        try:
            rev = await store.commit_garden(
                session.user_id, expected_rev=snap.rev, result=result, reason=reason, now=now
            )
        except StaleGardenError:
            continue
        return result, rev
    raise StaleGardenError("garden revision kept changing; giving up for a retry")


async def _rebuild(
    store: EvidenceStore,
    session: SessionRef,
    current: GardenState,
    incremental: RulesResult,
    profile: RulesProfile,
    now: datetime,
    known: set[str],
) -> RulesResult:
    replayed = replay(
        await store.accepted_observations(session.user_id), now, profile, known_concepts=known
    )
    changes: list[PlantChange] = []
    for key in sorted(set(replayed.state.plants) | set(current.plants)):
        new, old = replayed.state.plants.get(key), current.plants.get(key)
        if new == old:
            continue
        after = new or PlantState(concept_key=key)
        events = tuple(e for c in replayed.changes if c.concept_key == key for e in c.events)
        changes.append(
            PlantChange(
                concept_key=key,
                reason="assessment",
                status_before=old.status if old else PlantStatus.UNASSESSED,
                status_after=after.status,
                before=old,
                after=after,
                events=events,
            )
        )
    return dataclasses.replace(
        replayed,
        changes=tuple(changes),
        reassess=tuple(sorted({*replayed.reassess, *incremental.reassess}, key=str)),
    )


def _grew(result: RulesResult | None) -> set[Any]:
    if result is None:
        return set()
    return {e.assessment_id for c in result.changes for e in c.events}


_SKIP_TEXT = {
    "repeat_problem_family": "it repeated a problem type already counted",
    "retention_too_soon": "it came too soon after you learned it to count as recall",
    "retention_before_learning": "it needs an earlier independent explanation or solve first",
    "same_family_as_application": "transfer needs a different kind of problem",
    "missing_problem_family": "transfer needs a clearly different problem",
    "assisted_retention_not_counted": "recall with help does not count",
    "no_credit": "the answer did not show the idea yet",
    "unassessable": "it could not be assessed from the recording",
    "out_of_order": "newer evidence already covers this",
}


async def _reconcile_provisional(
    store: EvidenceStore,
    session: SessionRef,
    provisional: list[ProvisionalMemory],
    saved: list[tuple[Verdict, SavedAssessment]],
    grew: set[Any],
    garden: RulesResult | None,
) -> tuple[int, int]:
    """Solidify live glow that the full judge confirmed; retract the rest, with a reason."""
    by_key = {(v.concept_key, v.dimension): (v, s) for v, s in saved}
    skipped = {sk.assessment_id: sk.reason for sk in garden.skipped} if garden else {}
    confirmed = retracted = 0
    for memory in provisional:
        pair = by_key.get((memory.concept_key, memory.dimension))
        if pair is not None and pair[1].id in grew and pair[1].evidence_ids:
            await store.promote_memory(
                memory.memory_id, session.user_id, list(pair[1].evidence_ids)
            )
            await store.emit(
                session.id,
                session.user_id,
                "garden.provisional_confirmed",
                {"concept": memory.concept_key, "dimension": memory.dimension},
            )
            confirmed += 1
            continue
        if pair is None:
            why = "the full review found no clear evidence of it"
        elif pair[1].id in (garden.reassess if garden else ()):
            why = "the full review found the evidence ambiguous, so a re-check is queued"
        else:
            why = _SKIP_TEXT.get(skipped.get(pair[1].id, ""), "the full review did not confirm it")
        await store.dispute_memory(memory.memory_id, session.user_id)
        await store.append_memory(
            NewMemory(
                user_id=session.user_id,
                layer=MemoryLayer.SESSION,
                kind="provisional_retracted",
                content=(
                    f"Live growth on {memory.concept_key} ({memory.dimension}) "
                    f"was retracted: {why}."
                ),
                source=MemorySource.EVIDENCE_PIPELINE,
                source_session_id=session.id,
                status=MemoryStatus.ACCEPTED,
                data={
                    "concept_key": memory.concept_key,
                    "dimension": memory.dimension,
                    "reason": why,
                },
            )
        )
        await store.emit(
            session.id,
            session.user_id,
            "garden.provisional_retracted",
            {"concept": memory.concept_key, "dimension": memory.dimension, "reason": why},
        )
        retracted += 1
    return confirmed, retracted


async def _write_memories(
    store: EvidenceStore,
    session: SessionRef,
    saved: list[tuple[Verdict, SavedAssessment]],
    catalog: Mapping[str, ConceptInfo],
    grew: set[Any],
    reassess: set[Any],
) -> None:
    character = (
        Character(session.character) if session.character in Character._value2member_map_ else None
    )
    for v, s in saved:
        title = catalog[v.concept_key].title
        base: dict[str, Any] = {
            "concept_key": v.concept_key,
            "dimension": v.dimension,
            "assessment_id": str(s.id),
            "assistance": v.assistance.value,
        }
        if s.id in reassess:
            await store.append_memory(
                NewMemory(
                    user_id=session.user_id,
                    layer=MemoryLayer.SESSION,
                    kind="reassess_request",
                    content=(
                        f"The evidence on {title} ({v.dimension}) was ambiguous: "
                        "check it again next time."
                    ),
                    source=MemorySource.EVIDENCE_PIPELINE,
                    source_character=character,
                    source_session_id=session.id,
                    status=MemoryStatus.ACCEPTED,
                    data=base,
                )
            )
        elif s.id in grew and s.evidence_ids:
            how = "with help" if v.assistance.value == "assisted" else "on their own"
            await store.append_memory(
                NewMemory(
                    user_id=session.user_id,
                    layer=MemoryLayer.SKILLS,
                    kind=f"demonstrated_{v.dimension}",
                    content=(
                        f"{title}: {v.dimension} shown {how} ({v.outcome.value}). {v.rationale}"
                    ),
                    source=MemorySource.EVIDENCE_PIPELINE,
                    source_character=character,
                    source_session_id=session.id,
                    evidence_ids=s.evidence_ids,
                    status=MemoryStatus.ACCEPTED,
                    confidence=None if v.uncertainty is None else round(1 - v.uncertainty, 3),
                    data=base,
                )
            )
        if v.misconception and s.evidence_ids and s.id not in reassess:
            await store.append_memory(
                NewMemory(
                    user_id=session.user_id,
                    layer=MemoryLayer.KNOWLEDGE,
                    kind="misconception",
                    content=f"{title}: {v.misconception}",
                    source=MemorySource.EVIDENCE_PIPELINE,
                    source_character=character,
                    source_session_id=session.id,
                    evidence_ids=s.evidence_ids,
                    status=MemoryStatus.PROVISIONAL,  # tentative until later evidence agrees
                    data={**base, "tentative": True},
                )
            )


async def _finish(
    store: EvidenceStore,
    session: SessionRef,
    digest: str,
    status: str,
    extra: dict[str, Any],
    now: datetime,
) -> None:
    await store.patch_session(
        session.id,
        attributes={
            "post_call": {
                "transcript_hash": digest,
                "judged": True,
                "status": status,
                "at": now.isoformat(),
                **extra,
            }
        },
    )
    await store.emit(
        session.id,
        session.user_id,
        "evidence.pipeline_completed",
        {"status": status, **{k: v for k, v in extra.items() if k != "rejected"}},
    )
