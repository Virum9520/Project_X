"""Commitments: what a learner promised, and what they (or we) say happened.

Self-reported and observed completion are kept apart (`completion_source`, `reported_*`). A
self-report never becomes observed evidence, an observed completion is never downgraded by a
later self-report, and nothing here writes evidence or touches the garden: habit completion is
not technical mastery.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sg_core.accountability.scheduling import load_zone
from sg_core.accountability.store import AccountabilityStore
from sg_core.models.accountability import Commitment
from sg_core.models.enums import CommitmentStatus, CompletionSource

ReportedStatus = Literal["done", "partly_done", "not_done", "wants_to_change"]
MAX_DESCRIPTION = 300
MAX_NOTE = 400
MAX_OPEN = 10
PAST_TOLERANCE = timedelta(minutes=5)
MAX_HORIZON = timedelta(days=60)
_OPEN = (CommitmentStatus.OPEN,)


class CommitmentRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def parse_due_local(due_local: str, tz: str) -> datetime:
    """`2026-10-05T21:00` in the learner's zone -> UTC. A trailing offset is honoured."""
    try:
        parsed = datetime.fromisoformat(due_local.strip())
    except ValueError as exc:
        raise CommitmentRejected(
            "bad_due", "due_local must be ISO 8601, e.g. 2026-10-05T21:00"
        ) from exc
    zone: ZoneInfo = load_zone(tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(UTC)


async def log_commitment(
    store: AccountabilityStore,
    *,
    user_id: uuid.UUID,
    tz: str,
    description: str,
    due_local: str,
    confirmed_by_learner: bool,
    concept_key: str | None = None,
    session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> tuple[Commitment, bool]:
    """Save a confirmed commitment. Returns `(commitment, created)`; a retried tool call with the
    same text and due time returns the existing row."""
    now = now or datetime.now(UTC)
    if not confirmed_by_learner:
        raise CommitmentRejected("not_confirmed", "read it back and get a clear yes first")
    text = _clean(description, MAX_DESCRIPTION)
    if len(text) < 3:
        raise CommitmentRejected("bad_description", "describe the commitment")
    due_at = parse_due_local(due_local, tz)
    if due_at < now - PAST_TOLERANCE:
        raise CommitmentRejected("due_in_past", "that time has already passed")
    if due_at > now + MAX_HORIZON:
        raise CommitmentRejected("due_too_far", "commitments must fall due within 60 days")

    open_rows = await store.list_commitments(user_id, statuses=_OPEN)
    for row in open_rows:
        if (
            row.due_at == due_at
            and _clean(row.description, MAX_DESCRIPTION).casefold() == text.casefold()
        ):
            return row, False
    if len(open_rows) >= MAX_OPEN:
        raise CommitmentRejected("too_many_open", "finish or change an open commitment first")
    row = await store.add_commitment(
        user_id=user_id,
        description=text,
        due_at=due_at,
        concept_key=concept_key,
        session_id=session_id,
    )
    return row, True


async def report_progress(
    store: AccountabilityStore,
    *,
    user_id: uuid.UUID,
    commitment_id: uuid.UUID,
    status: ReportedStatus,
    learner_words: str | None = None,
    now: datetime | None = None,
) -> Commitment | None:
    """Record what the learner said. A self-report, stored separately from observed progress."""
    now = now or datetime.now(UTC)
    row = await store.get_commitment(commitment_id, user_id)
    if row is None:
        return None
    row.reported_status = status
    row.reported_note = _clean(learner_words, MAX_NOTE) if learner_words else None
    row.reported_at = now
    if row.status is CommitmentStatus.OPEN:
        if status == "done":
            row.status = CommitmentStatus.COMPLETED
            row.completion_source = CompletionSource.SELF_REPORTED
            row.completed_at = now
        elif status == "not_done" and row.due_at is not None and row.due_at <= now:
            row.status = CommitmentStatus.MISSED
        elif status == "wants_to_change":
            row.status = CommitmentStatus.CANCELLED  # replaced by a new commitment
        # partly_done, or not_done before the deadline: still open
    await store.save(row)
    return row


async def record_observed_completion(
    store: AccountabilityStore,
    *,
    user_id: uuid.UUID,
    commitment_id: uuid.UUID,
    now: datetime | None = None,
) -> Commitment | None:
    """The app saw it happen (verified by a trusted signal, not by the learner's word)."""
    now = now or datetime.now(UTC)
    row = await store.get_commitment(commitment_id, user_id)
    if row is None:
        return None
    if row.status in (CommitmentStatus.CANCELLED,):
        return row
    row.status = CommitmentStatus.COMPLETED
    row.completion_source = CompletionSource.OBSERVED
    row.completed_at = row.completed_at or now
    await store.save(row)
    return row
