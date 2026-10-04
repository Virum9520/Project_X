"""Check a judge's output before anything is stored: schema, ownership and evidence references.

The judge proposes; this module disposes. A verdict survives only if its concept is one this
session could assess, its enums are valid, every citation is a verbatim quote of the *learner's*
own turn in *this* conversation, and its assistance is at least as high as everything else on
record says (agent observation, hints given). Valid structure does not make a judgment correct;
it only guarantees the verdict is attributable and cannot cite words nobody said.
"""

import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from sg_core.evidence.transcript import looks_like_injection, normalize
from sg_core.evidence.types import (
    JUDGED_DIMENSIONS,
    AgentObservation,
    Citation,
    ConceptInfo,
    RawVerdict,
    Rejection,
    Transcript,
    Verdict,
)
from sg_core.models.enums import AssessmentOutcome, Assistance, Character, Dimension

MAX_CITATIONS = 4
MAX_QUOTE_CHARS = 400
MIN_QUOTE_CHARS = 3
MAX_RATIONALE_CHARS = 800
INJECTION_UNCERTAINTY = 0.9
_FAMILY = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
_ASSISTED_WORDS = {"assisted", "hinted", "heavily_assisted"}


@dataclass(frozen=True, slots=True)
class ValidationContext:
    transcript: Transcript
    catalog: Mapping[str, ConceptInfo]
    candidates: Collection[str]
    character: str
    observations: Sequence[AgentObservation] = ()
    # Concepts for which the learner was given a hint. A hint with no concept (None) covers
    # every concept in the session.
    hinted_concepts: Collection[str | None] = ()
    retention_concept: str | None = None


def _outcome(value: str) -> AssessmentOutcome | None:
    try:
        return AssessmentOutcome(value)
    except ValueError:
        return None


def _assistance(value: str) -> Assistance | None:
    if value == Assistance.INDEPENDENT.value:
        return Assistance.INDEPENDENT
    return Assistance.ASSISTED if value in _ASSISTED_WORDS else None


def _family(value: str | None) -> str | None:
    if value is None:
        return None
    slug = value.strip().lower().replace(" ", "_")
    return slug if _FAMILY.match(slug) else None


def _assistance_floor(raw: RawVerdict, ctx: ValidationContext) -> bool:
    if any(
        o.assisted and o.concept_key == raw.concept_key and o.dimension == raw.dimension
        for o in ctx.observations
    ):
        return True
    return raw.concept_key in ctx.hinted_concepts or None in ctx.hinted_concepts


def validate_verdicts(
    raw: Sequence[RawVerdict], ctx: ValidationContext
) -> tuple[list[Verdict], list[Rejection]]:
    accepted: list[Verdict] = []
    rejected: list[Rejection] = []

    def reject(r: RawVerdict, reason: str) -> None:
        rejected.append(Rejection(r.concept_key, r.dimension, reason))

    for r in raw:
        verdict = _validate_one(r, ctx, reject)
        if verdict is not None:
            accepted.append(verdict)

    # One verdict per (concept, dimension): keep the least uncertain, then the first listed.
    chosen: dict[tuple[str, str], int] = {}
    for i, v in enumerate(accepted):
        key = (v.concept_key, v.dimension)
        if key not in chosen or _unc(v) < _unc(accepted[chosen[key]]):
            chosen[key] = i
    keep = set(chosen.values())
    for i, v in enumerate(accepted):
        if i not in keep:
            rejected.append(Rejection(v.concept_key, v.dimension, "duplicate_verdict"))
    return [v for i, v in enumerate(accepted) if i in keep], rejected


def _unc(v: Verdict) -> float:
    return 1.0 if v.uncertainty is None else v.uncertainty


def _validate_one(r: RawVerdict, ctx: ValidationContext, reject) -> Verdict | None:  # type: ignore[no-untyped-def]
    if r.concept_key not in ctx.catalog:
        reject(r, "unknown_concept")
        return None
    if r.concept_key not in ctx.candidates:
        reject(r, "concept_not_in_scope")
        return None
    if r.dimension not in JUDGED_DIMENSIONS:
        reject(r, "unknown_dimension")
        return None
    outcome = _outcome(r.outcome)
    if outcome is None:
        reject(r, "invalid_outcome")
        return None
    assistance = _assistance(r.assistance)
    if assistance is None:
        reject(r, "invalid_assistance")
        return None
    rationale = " ".join(r.rationale.split())[:MAX_RATIONALE_CHARS]
    if not rationale:
        reject(r, "missing_rationale")
        return None
    u = r.uncertainty
    if u is None or math.isnan(u) or not 0.0 <= u <= 1.0:
        reject(r, "invalid_uncertainty")
        return None
    if ctx.character == Character.BHIMA.value and (
        r.dimension != Dimension.RETENTION.value or r.concept_key != ctx.retention_concept
    ):
        # Bhima only asks the one retention question; the rest of the call is habit talk.
        reject(r, "outside_retention_scope")
        return None

    citations: list[Citation] = []
    flags: list[str] = []
    for turn_index, quote in r.citations:
        turn = ctx.transcript.turn(turn_index)
        text = " ".join(quote.split())[:MAX_QUOTE_CHARS]
        if turn is None or turn.role != "learner" or len(text) < MIN_QUOTE_CHARS:
            continue
        if normalize(text) not in normalize(turn.text):
            continue
        citations.append(Citation(turn=turn_index, quote=text))
        if len(citations) == MAX_CITATIONS:
            break
    if not citations and outcome is not AssessmentOutcome.UNASSESSABLE:
        reject(r, "no_verified_evidence")
        return None
    if any(looks_like_injection(c.quote) for c in citations):
        # The learner's words address the grader. Never grow from that: make it ambiguous.
        flags.append("injection_suspected")
        u = max(u, INJECTION_UNCERTAINTY)
    if _assistance_floor(r, ctx) and assistance is Assistance.INDEPENDENT:
        assistance = Assistance.ASSISTED
        flags.append("assistance_floor")

    return Verdict(
        concept_key=r.concept_key,
        dimension=r.dimension,
        outcome=outcome,
        assistance=assistance,
        citations=tuple(citations),
        rationale=rationale,
        uncertainty=u,
        problem_family=_family(r.problem_family),
        misconception=" ".join(r.misconception.split())[:300] if r.misconception else None,
        flags=tuple(flags),
    )
