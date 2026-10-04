"""Append-only memory writes.

Rows are never edited in place. A correction or promotion inserts a new revision and marks the
old row `superseded` with `superseded_by_id` pointing at it, so history can be replayed. The only
other mutations are `status` -> `disputed`, backfilled embeddings (derived data) and the
learner's right to delete their own private reflections.

Rules enforced here:
- Evidence ids must belong to the same learner.
- Skills memories cannot be `accepted` without evidence, and a provisional memory is promoted
  only by citing evidence (the evidence pipeline's job, never an agent's).
- A learner's own correction of a non-skills memory is accepted immediately (it is their fact);
  a corrected skills memory goes back to provisional, because a claim never establishes mastery.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, any_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.logging import get_logger
from sg_core.memory.embeddings import EmbeddingProvider, get_embedding_provider
from sg_core.memory.errors import MemoryNotFound, MemoryRuleViolation
from sg_core.models.enums import Character, MemoryLayer, MemorySource, MemoryStatus
from sg_core.models.evidence import EvidenceItem
from sg_core.models.memory import Memory

log = get_logger(__name__)

MAX_CONTENT_CHARS = 2000


@dataclass(frozen=True)
class NewMemory:
    user_id: uuid.UUID
    layer: MemoryLayer
    kind: str
    content: str
    source: MemorySource
    source_character: Character | None = None
    source_session_id: uuid.UUID | None = None
    evidence_ids: Sequence[uuid.UUID] = ()
    status: MemoryStatus = MemoryStatus.PROVISIONAL
    confidence: float | None = None
    visible_to: Sequence[str] | None = None
    expires_at: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)


def active_filter(
    user_id: uuid.UUID, character: str | None = None, now: datetime | None = None
) -> list[ColumnElement[bool]]:
    """Memories that may be read now: not superseded, not expired, visible to `character`."""
    moment = now or datetime.now(UTC)
    clauses: list[ColumnElement[bool]] = [
        Memory.user_id == user_id,
        Memory.status != MemoryStatus.SUPERSEDED.value,
        or_(Memory.expires_at.is_(None), Memory.expires_at > moment),
    ]
    if character is not None:
        clauses.append(
            or_(Memory.visible_to.is_(None), literal(character) == any_(Memory.visible_to))
        )
    return clauses


class MemoryStore:
    def __init__(self, session: AsyncSession, embedder: EmbeddingProvider | None = None) -> None:
        self.session = session
        self.embedder = embedder or get_embedding_provider()

    # ── writes ──
    async def append(self, new: NewMemory) -> Memory:
        content = " ".join(new.content.split())
        if not content:
            raise MemoryRuleViolation("memory content is empty")
        if len(content) > MAX_CONTENT_CHARS:
            raise MemoryRuleViolation(f"memory content exceeds {MAX_CONTENT_CHARS} characters")
        if new.confidence is not None and not 0 <= new.confidence <= 1:
            raise MemoryRuleViolation("confidence must be between 0 and 1")
        if new.status is MemoryStatus.SUPERSEDED:
            raise MemoryRuleViolation("new memories cannot start superseded")
        evidence = list(dict.fromkeys(new.evidence_ids))
        await self._check_evidence(new.user_id, evidence)
        if new.status is MemoryStatus.ACCEPTED and new.layer is MemoryLayer.SKILLS and not evidence:
            raise MemoryRuleViolation("accepted skills memories must cite evidence")

        memory = Memory(
            user_id=new.user_id,
            layer=new.layer,
            kind=new.kind,
            content=content,
            data=dict(new.data),
            source=new.source,
            source_character=new.source_character,
            source_session_id=new.source_session_id,
            evidence_ids=evidence,
            status=new.status,
            confidence=new.confidence,
            visible_to=list(new.visible_to) if new.visible_to is not None else None,
            expires_at=new.expires_at,
        )
        await self._embed(memory)
        self.session.add(memory)
        await self.session.flush()
        return memory

    async def correct(
        self,
        memory_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str,
        *,
        source: MemorySource = MemorySource.USER,
        evidence_ids: Sequence[uuid.UUID] = (),
    ) -> Memory:
        """Replace a memory with a corrected revision. The old row stays, marked superseded."""
        old = await self._get_live(memory_id, user_id)
        accepted = source is MemorySource.USER and old.layer is not MemoryLayer.SKILLS
        new = await self.append(
            NewMemory(
                user_id=user_id,
                layer=old.layer,
                kind=old.kind,
                content=content,
                source=source,
                source_character=old.source_character,
                source_session_id=old.source_session_id,
                evidence_ids=[*old.evidence_ids, *evidence_ids],
                status=MemoryStatus.ACCEPTED if accepted else MemoryStatus.PROVISIONAL,
                confidence=old.confidence,
                visible_to=old.visible_to,
                expires_at=old.expires_at,
                data={**old.data, "corrects": str(old.id)},
            )
        )
        await self._supersede(old, new)
        return new

    async def promote(
        self, memory_id: uuid.UUID, user_id: uuid.UUID, evidence_ids: Sequence[uuid.UUID]
    ) -> Memory:
        """Accept a provisional or disputed memory as a new revision. Requires evidence."""
        old = await self._get_live(memory_id, user_id)
        if old.status is MemoryStatus.ACCEPTED:
            return old
        merged = list(dict.fromkeys([*old.evidence_ids, *evidence_ids]))
        if not merged:
            raise MemoryRuleViolation("promotion requires at least one evidence item")
        new = await self.append(
            NewMemory(
                user_id=user_id,
                layer=old.layer,
                kind=old.kind,
                content=old.content,
                source=MemorySource.EVIDENCE_PIPELINE,
                source_character=old.source_character,
                source_session_id=old.source_session_id,
                evidence_ids=merged,
                status=MemoryStatus.ACCEPTED,
                confidence=old.confidence,
                visible_to=old.visible_to,
                expires_at=old.expires_at,
                data={**old.data, "promoted_from": str(old.id)},
            )
        )
        await self._supersede(old, new)
        return new

    async def dispute(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory:
        """Flag a memory as disputed; it stays readable but ranks low and is labelled."""
        memory = await self._get_live(memory_id, user_id)
        memory.status = MemoryStatus.DISPUTED
        await self.session.flush()
        return memory

    async def forget_private(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete one of the learner's own private reflections (the only hard delete)."""
        memory = await self._get(memory_id, user_id)
        if memory.layer is not MemoryLayer.PRIVATE:
            raise MemoryRuleViolation("only private reflections can be deleted; correct instead")
        await self.session.delete(memory)
        await self.session.flush()

    async def backfill_embeddings(self, limit: int = 100) -> int:
        """Embed rows written while the provider was unavailable. Returns rows updated."""
        rows = (
            await self.session.scalars(
                select(Memory)
                .where(Memory.embedding.is_(None))
                .order_by(Memory.created_at)
                .limit(limit)
            )
        ).all()
        for row in rows:
            await self._embed(row)
        await self.session.flush()
        return sum(1 for row in rows if row.embedding is not None)

    # ── reads ──
    async def list_active(
        self,
        user_id: uuid.UUID,
        *,
        character: str | None = None,
        layers: Sequence[MemoryLayer] | None = None,
        kinds: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        query = select(Memory).where(*active_filter(user_id, character))
        if layers:
            query = query.where(Memory.layer.in_([layer.value for layer in layers]))
        if kinds:
            query = query.where(Memory.kind.in_(list(kinds)))
        query = query.order_by(Memory.created_at.desc()).limit(limit)
        return list((await self.session.scalars(query)).all())

    async def history(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> list[Memory]:
        """The whole revision chain containing `memory_id`, oldest first."""
        chain = [await self._get(memory_id, user_id)]
        while True:
            previous = await self.session.scalar(
                select(Memory).where(
                    Memory.user_id == user_id, Memory.superseded_by_id == chain[0].id
                )
            )
            if previous is None:
                break
            chain.insert(0, previous)
        while chain[-1].superseded_by_id is not None:
            chain.append(await self._get(chain[-1].superseded_by_id, user_id))
        return chain

    async def impact(self, memory: Memory) -> list[str]:
        """Concept keys a memory touches (via its evidence and `data.concept_key`), so the
        dashboard can show which plants a correction affects."""
        from sg_core.models.curriculum import Concept

        keys: set[str] = set()
        concept_key = memory.data.get("concept_key")
        if isinstance(concept_key, str):
            keys.add(concept_key)
        if memory.evidence_ids:
            rows = await self.session.scalars(
                select(Concept.key)
                .join(EvidenceItem, EvidenceItem.concept_id == Concept.id)
                .where(EvidenceItem.id.in_(list(memory.evidence_ids)))
            )
            keys.update(rows.all())
        return sorted(keys)

    # ── internals ──
    async def _get(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory:
        memory = await self.session.scalar(
            select(Memory).where(and_(Memory.id == memory_id, Memory.user_id == user_id))
        )
        if memory is None:
            raise MemoryNotFound(str(memory_id))
        return memory

    async def _get_live(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> Memory:
        memory = await self._get(memory_id, user_id)
        if memory.status is MemoryStatus.SUPERSEDED:
            raise MemoryRuleViolation("memory is already superseded; use the latest revision")
        return memory

    async def _supersede(self, old: Memory, new: Memory) -> None:
        old.status = MemoryStatus.SUPERSEDED
        old.superseded_by_id = new.id
        await self.session.flush()

    async def _check_evidence(self, user_id: uuid.UUID, evidence_ids: Sequence[uuid.UUID]) -> None:
        if not evidence_ids:
            return
        found = set(
            (
                await self.session.scalars(
                    select(EvidenceItem.id).where(
                        EvidenceItem.user_id == user_id, EvidenceItem.id.in_(evidence_ids)
                    )
                )
            ).all()
        )
        missing = [str(e) for e in evidence_ids if e not in found]
        if missing:
            raise MemoryRuleViolation(f"unknown evidence for this learner: {', '.join(missing)}")

    async def _embed(self, memory: Memory) -> None:
        try:
            [vector] = await self.embedder.embed([memory.content])
        except Exception:  # a provider outage must not block recording what the learner said
            log.warning("memory.embed_failed", exc_info=True)
            return
        memory.embedding = vector
        memory.embedding_model = self.embedder.model
