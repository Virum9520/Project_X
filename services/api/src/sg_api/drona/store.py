"""Database access for the Drona loop: the `sessions` row and concept rubrics for questions.

Every method takes the Clerk user ID (the identity in tokens) and scopes SQL to that learner's
`users.id`. A learner with no `users` row yet (C01 mirrors it on the first `/v1/me`) cannot own
a row, so those calls report "not stored" instead of failing: the voice session still works,
only its records are missing. Outside local and test environments a database error is surfaced.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_api.drona.questions import ConceptRubric
from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.models.curriculum import Concept, Curriculum, Rubric
from sg_core.models.enums import Character, CurriculumStatus, SessionStatus
from sg_core.models.identity import User
from sg_core.models.knowledge import Document, DocumentVersion
from sg_core.models.sessions import Session as SessionRow

log = get_logger(__name__)

# Panel sessions are stored as Vidura with mode `panel_interview` (see docs/PROGRESS.md).
STORED_CHARACTER = {"panel": "vidura"}
DEFAULT_MODE = {
    "drona": "concept_exam",
    "arjuna": "technical_interview",
    "vidura": "hr_interview",
    "panel": "panel_interview",
    "bhima": "accountability_call",
    "krishna": "morning_talk",
    "sanjaya": "weekly_recap",
}
LIVE_STATUSES = (SessionStatus.CREATED, SessionStatus.ACTIVE)


@dataclass(frozen=True)
class NewSession:
    clerk_user_id: str
    session_id: uuid.UUID
    character: str
    mode: str
    agent_id: str
    conversation_id: str | None
    focus_concept: str | None
    is_test: bool = False


BindResult = Literal["bound", "same", "conflict", "missing"]


class SessionStore(Protocol):
    async def create(self, new: NewSession) -> bool:
        """Persist the row. False when it could not be stored (no `users` row yet)."""

    async def end(self, clerk_user_id: str, session_id: str, status: SessionStatus) -> bool:
        """Mark a live session finished. Idempotent. False when there is no such session."""

    async def bind_conversation(
        self, clerk_user_id: str, session_id: str, conversation_id: str
    ) -> BindResult: ...

    async def session_focus(self, clerk_user_id: str, session_id: str) -> str | None:
        """The focus concept key the session was started with."""

    async def concept_rubric(self, concept_key: str) -> ConceptRubric | None:
        """Concept and rubric in the active curriculum."""


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _user_id(db: AsyncSession, clerk_user_id: str) -> uuid.UUID | None:
    return await db.scalar(
        select(User.id).where(User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None))
    )


async def active_curriculum_id(db: AsyncSession) -> uuid.UUID | None:
    return await db.scalar(
        select(Curriculum.id)
        .where(Curriculum.status == CurriculumStatus.ACTIVE)
        .order_by(Curriculum.created_at.desc())
        .limit(1)
    )


async def newest_active_document_version(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    """The version the learner's study material is at right now; the session is pinned to it so
    its judge later reads the same text even if a newer upload goes live mid-call."""
    return await db.scalar(
        select(DocumentVersion.id)
        .join(Document, Document.active_version_id == DocumentVersion.id)
        .where(Document.user_id == user_id, Document.deleted_at.is_(None))
        .order_by(DocumentVersion.activated_at.desc().nulls_last())
        .limit(1)
    )


class DbSessionStore:
    async def create(self, new: NewSession) -> bool:
        async with get_sessionmaker()() as db:
            user_id = await _user_id(db, new.clerk_user_id)
            if user_id is None:
                log.info(
                    "sessions.not_stored", reason="no users row", session_id=str(new.session_id)
                )
                return False
            stored = STORED_CHARACTER.get(new.character, new.character)
            attributes: dict[str, Any] = {"requested_character": new.character}
            if new.focus_concept:
                attributes["focus_concept"] = new.focus_concept
            db.add(
                SessionRow(
                    id=new.session_id,
                    user_id=user_id,
                    character=Character(stored),
                    mode=new.mode,
                    status=SessionStatus.CREATED,
                    agent_id=new.agent_id,
                    el_conversation_id=new.conversation_id,
                    curriculum_id=await active_curriculum_id(db),
                    document_version_id=await newest_active_document_version(db, user_id),
                    is_test=new.is_test,
                    started_at=datetime.now(UTC),
                    attributes=attributes,
                )
            )
            await db.commit()
            return True

    async def _owned(
        self, db: AsyncSession, clerk_user_id: str, session_id: str
    ) -> SessionRow | None:
        sid = parse_uuid(session_id)
        user_id = await _user_id(db, clerk_user_id)
        if sid is None or user_id is None:
            return None
        return await db.scalar(
            select(SessionRow).where(SessionRow.id == sid, SessionRow.user_id == user_id)
        )

    async def end(self, clerk_user_id: str, session_id: str, status: SessionStatus) -> bool:
        async with get_sessionmaker()() as db:
            row = await self._owned(db, clerk_user_id, session_id)
            if row is None:
                return False
            if row.status in LIVE_STATUSES:
                now = datetime.now(UTC)
                row.status = status
                row.ended_at = now
                if row.started_at is not None:
                    row.duration_seconds = max(0, int((now - row.started_at).total_seconds()))
                await db.commit()
            return True

    async def bind_conversation(
        self, clerk_user_id: str, session_id: str, conversation_id: str
    ) -> BindResult:
        async with get_sessionmaker()() as db:
            row = await self._owned(db, clerk_user_id, session_id)
            if row is None:
                return "missing"
            if row.el_conversation_id == conversation_id:
                return "same"
            if row.el_conversation_id is not None:
                return "conflict"
            taken = await db.scalar(
                select(SessionRow.id).where(SessionRow.el_conversation_id == conversation_id)
            )
            if taken is not None:
                return "conflict"
            row.el_conversation_id = conversation_id
            if row.status is SessionStatus.CREATED:
                row.status = SessionStatus.ACTIVE
            await db.commit()
            return "bound"

    async def session_focus(self, clerk_user_id: str, session_id: str) -> str | None:
        async with get_sessionmaker()() as db:
            row = await self._owned(db, clerk_user_id, session_id)
            focus = (row.attributes or {}).get("focus_concept") if row else None
            return focus if isinstance(focus, str) else None

    async def concept_rubric(self, concept_key: str) -> ConceptRubric | None:
        async with get_sessionmaker()() as db:
            curriculum_id = await active_curriculum_id(db)
            if curriculum_id is None:
                return None
            concept = await db.scalar(
                select(Concept).where(
                    Concept.curriculum_id == curriculum_id, Concept.key == concept_key
                )
            )
            if concept is None:
                return None
            criteria = await db.scalar(
                select(Rubric.criteria)
                .where(Rubric.concept_id == concept.id, Rubric.dimension.is_(None))
                .order_by(Rubric.version.desc())
                .limit(1)
            )
            listed = {
                name: [str(v) for v in values]
                for name, values in (criteria or {}).items()
                if isinstance(values, list)
            }
            return ConceptRubric(concept.key, concept.title, concept.summary or "", listed)


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = DbSessionStore()
    return _store
