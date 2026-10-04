"""Consent records (`voice_consents`). Revocation keeps the row but erases recording and voice."""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.db import get_sessionmaker
from sg_core.models.accountability import VoiceConsent


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    consent_ver: str
    recording_s3: str  # ObjectStore key; empty once revoked (recording deleted)
    phrase_verified: bool
    verified_transcript: str | None
    voice_id: str | None
    created_at: datetime
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.phrase_verified and self.voice_id is not None


class ConsentStore(Protocol):
    async def add(self, record: ConsentRecord) -> None: ...
    async def set_voice(self, record_id: uuid.UUID, voice_id: str) -> ConsentRecord: ...
    async def revoke(self, record_id: uuid.UUID, *, at: datetime) -> ConsentRecord: ...
    async def delete(self, record_id: uuid.UUID) -> None: ...
    async def get_current(self, user_id: uuid.UUID) -> ConsentRecord | None:
        """The learner's unrevoked consent record, if any."""
        ...

    async def history(self, user_id: uuid.UUID) -> list[ConsentRecord]:
        """Every record, newest first (revoked ones included)."""
        ...


class InMemoryConsentStore:
    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, ConsentRecord] = {}

    async def add(self, record: ConsentRecord) -> None:
        self._rows[record.id] = record

    async def set_voice(self, record_id: uuid.UUID, voice_id: str) -> ConsentRecord:
        self._rows[record_id] = replace(self._rows[record_id], voice_id=voice_id)
        return self._rows[record_id]

    async def revoke(self, record_id: uuid.UUID, *, at: datetime) -> ConsentRecord:
        self._rows[record_id] = replace(
            self._rows[record_id],
            revoked_at=at,
            recording_s3="",
            verified_transcript=None,
            voice_id=None,
        )
        return self._rows[record_id]

    async def delete(self, record_id: uuid.UUID) -> None:
        self._rows.pop(record_id, None)

    async def get_current(self, user_id: uuid.UUID) -> ConsentRecord | None:
        rows = [r for r in self._rows.values() if r.user_id == user_id and r.revoked_at is None]
        return max(rows, key=lambda r: r.created_at, default=None)

    async def history(self, user_id: uuid.UUID) -> list[ConsentRecord]:
        rows = [r for r in self._rows.values() if r.user_id == user_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)


def _record(row: VoiceConsent) -> ConsentRecord:
    return ConsentRecord(
        id=row.id,
        user_id=row.user_id,
        consent_ver=row.consent_ver,
        recording_s3=row.recording_s3,
        phrase_verified=row.phrase_verified,
        verified_transcript=row.verified_transcript,
        voice_id=row.voice_id,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


class DbConsentStore:
    """Each call is its own short transaction."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._maker = sessionmaker or get_sessionmaker()

    async def add(self, record: ConsentRecord) -> None:
        async with self._maker() as session, session.begin():
            session.add(
                VoiceConsent(
                    id=record.id,
                    user_id=record.user_id,
                    consent_ver=record.consent_ver,
                    recording_s3=record.recording_s3,
                    phrase_verified=record.phrase_verified,
                    verified_transcript=record.verified_transcript,
                    voice_id=record.voice_id,
                    created_at=record.created_at,
                )
            )

    @staticmethod
    async def _load(session: AsyncSession, record_id: uuid.UUID) -> VoiceConsent:
        row = await session.get(VoiceConsent, record_id, with_for_update=True)
        if row is None:
            raise KeyError(record_id)
        return row

    async def set_voice(self, record_id: uuid.UUID, voice_id: str) -> ConsentRecord:
        async with self._maker() as session, session.begin():
            row = await self._load(session, record_id)
            row.voice_id = voice_id
            return _record(row)

    async def revoke(self, record_id: uuid.UUID, *, at: datetime) -> ConsentRecord:
        async with self._maker() as session, session.begin():
            row = await self._load(session, record_id)
            row.revoked_at = at
            row.recording_s3 = ""
            row.verified_transcript = None
            row.voice_id = None
            return _record(row)

    async def delete(self, record_id: uuid.UUID) -> None:
        async with self._maker() as session, session.begin():
            row = await session.get(VoiceConsent, record_id)
            if row is not None:
                await session.delete(row)

    async def get_current(self, user_id: uuid.UUID) -> ConsentRecord | None:
        async with self._maker() as session:
            row = await session.scalar(
                select(VoiceConsent)
                .where(VoiceConsent.user_id == user_id, VoiceConsent.revoked_at.is_(None))
                .order_by(VoiceConsent.created_at.desc())
                .limit(1)
            )
            return _record(row) if row else None

    async def history(self, user_id: uuid.UUID) -> list[ConsentRecord]:
        async with self._maker() as session:
            rows = await session.scalars(
                select(VoiceConsent)
                .where(VoiceConsent.user_id == user_id)
                .order_by(VoiceConsent.created_at.desc())
            )
            return [_record(r) for r in rows]
