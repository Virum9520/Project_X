"""`AdminStore` on Postgres. Read-mostly aggregates over the core tables.

Cost rule (shared interface from C03): only `cost_entries` with `superseded_by_id IS NULL` count,
so a reconciled entry replaces the estimate it superseded instead of adding to it.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from sg_api.admin.schemas import (
    AgentRow,
    AuditPage,
    AuditRow,
    BudgetStatus,
    CallRow,
    CallsReport,
    ConsentInfo,
    CostGroup,
    CostGroupBy,
    CostReport,
    DailyCost,
    FailedEvent,
    Freshness,
    Overview,
    QualityReport,
    ScheduleInfo,
    UsageTotals,
    UserDetail,
    UserPage,
    UserRow,
    UserSessionRow,
)
from sg_api.admin.store import CooldownError, TestCallRecord
from sg_api.admin.util import (
    escape_like,
    mask_email,
    mask_phone,
    month_bounds,
    project_month_end,
    usd,
)
from sg_core.economics.budget import (
    budget_key_for,
    committed_usd,
    monthly_limit_usd,
    release,
    reserve,
)
from sg_core.identity.db import AUDIT_META_KEY
from sg_core.models.accountability import CallAttempt, CallOccurrence, CallSchedule, VoiceConsent
from sg_core.models.economics import BudgetReservation, CostEntry, UsageEvent
from sg_core.models.enums import (
    AssessmentStatus,
    CallChannelKind,
    CallState,
    Character,
    CostCenter,
    DisputeStatus,
    ProviderEventStatus,
    ReservationStatus,
    SessionStatus,
)
from sg_core.models.evidence import Assessment, AssessmentDispute, PlantState
from sg_core.models.identity import AuditLog, Profile, User
from sg_core.models.sessions import ProviderEvent
from sg_core.models.sessions import Session as VoiceSession
from sg_core.settings import Settings

Sessions = async_sessionmaker[AsyncSession]

LIVE = CostEntry.superseded_by_id.is_(None)
UPCOMING_STATES = (CallState.SCHEDULED, CallState.QUEUED)
ACTIVE_STATES = (CallState.DISPATCHING, CallState.RINGING, CallState.CONNECTED)
MAX_ERROR_CHARS = 300


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


async def _one[T](session: AsyncSession, stmt: Select[Any], default: T) -> T:
    value = await session.scalar(stmt)
    return default if value is None else value


class SqlAdminStore:
    def __init__(self, sessions: Sessions, settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def ping(self) -> None:
        async with self._sessions() as s:
            await s.scalar(select(1))

    # ── budgets ──
    async def developer_budget(self, limit_usd: Decimal, now: datetime) -> BudgetStatus:
        key = budget_key_for(CostCenter.DEVELOPER, at=now)
        async with self._sessions() as s:
            committed = await committed_usd(s, key, now)
        return BudgetStatus(key=key, limit_usd=usd(limit_usd), committed_usd=usd(committed))

    # ── overview ──
    async def overview(self, now: datetime) -> Overview:
        month_start, _ = month_bounds(now)
        d30, d7 = now - timedelta(days=30), now - timedelta(days=7)
        async with self._sessions() as s:
            active = await _one(
                s,
                select(func.count(func.distinct(VoiceSession.user_id))).where(
                    VoiceSession.created_at >= d30, VoiceSession.is_test.is_(False)
                ),
                0,
            )
            completed = await _one(
                s,
                select(func.count()).where(
                    VoiceSession.created_at >= d30,
                    VoiceSession.is_test.is_(False),
                    VoiceSession.status == SessionStatus.COMPLETED,
                ),
                0,
            )
            rows = (
                await s.execute(
                    select(CostEntry.cost_center, func.sum(CostEntry.usd_amount))
                    .where(LIVE, CostEntry.created_at >= month_start)
                    .group_by(CostEntry.cost_center)
                )
            ).all()
            by_center = {str(c.value if hasattr(c, "value") else c): usd(v) for c, v in rows}
            spend = round(sum(by_center.values()), 6)
            failed_sessions = await _one(
                s,
                select(func.count()).where(
                    VoiceSession.created_at >= d7, VoiceSession.status == SessionStatus.FAILED
                ),
                0,
            )
            failed_calls = await _one(
                s,
                select(func.count()).where(
                    CallAttempt.created_at >= d7, CallAttempt.state == CallState.FAILED
                ),
                0,
            )
            failed_events = await _one(
                s,
                select(func.count()).where(ProviderEvent.status == ProviderEventStatus.FAILED),
                0,
            )
            freshness = Freshness(
                usage_events_at=await s.scalar(select(func.max(UsageEvent.occurred_at))),
                cost_entries_at=await s.scalar(select(func.max(CostEntry.created_at))),
                sessions_at=await s.scalar(select(func.max(VoiceSession.created_at))),
                provider_events_at=await s.scalar(select(func.max(ProviderEvent.received_at))),
            )
            dev_key = budget_key_for(CostCenter.DEVELOPER, at=now)
            dev_limit = monthly_limit_usd(CostCenter.DEVELOPER, self._settings)
            dev = BudgetStatus(
                key=dev_key,
                limit_usd=usd(dev_limit),
                committed_usd=usd(await committed_usd(s, dev_key, now)),
            )
        return Overview(
            generated_at=now,
            period=now.strftime("%Y-%m"),
            active_users_30d=active,
            completed_sessions_30d=completed,
            spend_month_to_date_usd=spend,
            projected_month_end_usd=project_month_end(spend, now),
            spend_by_cost_center=by_center,
            failed_sessions_7d=failed_sessions,
            failed_calls_7d=failed_calls,
            failed_provider_events=failed_events,
            developer_budget=dev,
            freshness=freshness,
        )

    # ── users ──
    async def list_users(self, q: str | None, limit: int, offset: int) -> UserPage:
        month_start, _ = month_bounds(datetime.now(UTC))
        sessions_n = (
            select(func.count())
            .where(VoiceSession.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        spend = (
            select(func.coalesce(func.sum(CostEntry.usd_amount), 0))
            .where(CostEntry.user_id == User.id, LIVE, CostEntry.created_at >= month_start)
            .correlate(User)
            .scalar_subquery()
        )
        filters: list[ColumnElement[bool]] = [User.deleted_at.is_(None)]
        if q and q.strip():
            like = f"%{escape_like(q.strip())}%"
            filters.append(
                or_(
                    User.email.ilike(like, escape="\\"),
                    User.display_name.ilike(like, escape="\\"),
                )
            )
        async with self._sessions() as s:
            total = await _one(s, select(func.count()).select_from(User).where(*filters), 0)
            rows = (
                await s.execute(
                    select(User, Profile.onboarded_at, sessions_n, spend)
                    .outerjoin(Profile, Profile.user_id == User.id)
                    .where(*filters)
                    .order_by(User.created_at.desc(), User.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        items = [
            UserRow(
                id=str(u.id),
                email_masked=mask_email(u.email),
                display_name=u.display_name,
                created_at=u.created_at,
                onboarded=onboarded is not None,
                sessions=int(n or 0),
                spend_month_to_date_usd=usd(sp),
            )
            for u, onboarded, n, sp in rows
        ]
        return UserPage(items=items, total=total, limit=limit, offset=offset)

    async def get_user(self, user_id: uuid.UUID, now: datetime) -> UserDetail | None:
        month_start, _ = month_bounds(now)
        async with self._sessions() as s:
            user = await s.get(User, user_id)
            if user is None:
                return None
            profile = await s.get(Profile, user_id)
            plant_rows = (
                await s.execute(
                    select(PlantState.status, func.count())
                    .where(PlantState.user_id == user_id)
                    .group_by(PlantState.status)
                )
            ).all()
            sessions_total = await _one(
                s, select(func.count()).where(VoiceSession.user_id == user_id), 0
            )
            open_disputes = await _one(
                s,
                select(func.count())
                .select_from(AssessmentDispute)
                .join(Assessment, Assessment.id == AssessmentDispute.assessment_id)
                .where(
                    Assessment.user_id == user_id, AssessmentDispute.status == DisputeStatus.OPEN
                ),
                0,
            )
            comp_rows = (
                await s.execute(
                    select(CostEntry.component, func.sum(CostEntry.usd_amount))
                    .where(CostEntry.user_id == user_id, LIVE, CostEntry.created_at >= month_start)
                    .group_by(CostEntry.component)
                    .order_by(func.sum(CostEntry.usd_amount).desc())
                )
            ).all()
            by_component = {c: usd(v) for c, v in comp_rows}
            key = budget_key_for(CostCenter.LEARNER, user_id, now)
            budget = BudgetStatus(
                key=key,
                limit_usd=usd(monthly_limit_usd(CostCenter.LEARNER, self._settings)),
                committed_usd=usd(await committed_usd(s, key, now)),
            )
            schedules = (
                await s.scalars(
                    select(CallSchedule)
                    .where(CallSchedule.user_id == user_id)
                    .order_by(CallSchedule.created_at)
                )
            ).all()
            consent = (
                await s.scalars(
                    select(VoiceConsent)
                    .where(VoiceConsent.user_id == user_id)
                    .order_by(VoiceConsent.created_at.desc())
                    .limit(1)
                )
            ).first()
            recent = (
                await s.scalars(
                    select(VoiceSession)
                    .where(VoiceSession.user_id == user_id)
                    .order_by(VoiceSession.created_at.desc())
                    .limit(10)
                )
            ).all()
        return UserDetail(
            id=str(user.id),
            email_masked=mask_email(user.email),
            display_name=user.display_name,
            timezone=user.timezone,
            created_at=user.created_at,
            deleted_at=user.deleted_at,
            major=profile.major if profile else None,
            experience_level=profile.experience_level if profile else None,
            target_role=profile.target_role if profile else None,
            onboarded_at=profile.onboarded_at if profile else None,
            plant_status_counts={str(st.value): int(n) for st, n in plant_rows},
            sessions_total=sessions_total,
            open_disputes=open_disputes,
            spend_month_to_date_usd=round(sum(by_component.values()), 6),
            spend_by_component=by_component,
            budget=budget,
            schedules=[
                ScheduleInfo(
                    id=str(sc.id),
                    channel=sc.channel.value,
                    destination_masked=mask_phone(sc.destination),
                    destination_verified=sc.destination_verified_at is not None,
                    tz=sc.tz,
                    local_time=sc.local_time.strftime("%H:%M"),
                    days=list(sc.days),
                    enabled=sc.enabled,
                    max_duration_seconds=sc.max_duration_seconds,
                    consent_ver=sc.consent_ver,
                )
                for sc in schedules
            ],
            voice_consent=(
                ConsentInfo(
                    consent_ver=consent.consent_ver,
                    phrase_verified=consent.phrase_verified,
                    has_voice=consent.voice_id is not None and consent.revoked_at is None,
                    created_at=consent.created_at,
                    revoked_at=consent.revoked_at,
                )
                if consent
                else None
            ),
            recent_sessions=[
                UserSessionRow(
                    id=str(r.id),
                    character=r.character.value,
                    mode=r.mode,
                    status=r.status.value,
                    is_test=r.is_test,
                    started_at=r.started_at,
                    duration_seconds=r.duration_seconds,
                )
                for r in recent
            ],
        )

    # ── costs ──
    async def costs(
        self, start: date, end: date, group_by: CostGroupBy, now: datetime
    ) -> CostReport:
        lo, hi = _day_start(start), _day_start(end) + timedelta(days=1)
        in_range = and_(LIVE, CostEntry.created_at >= lo, CostEntry.created_at < hi)
        total_usd = func.sum(CostEntry.usd_amount)

        async with self._sessions() as s:
            if group_by == "model":
                key_col = func.coalesce(UsageEvent.model, "unknown")
                stmt = (
                    select(key_col, key_col, total_usd, func.count())
                    .select_from(CostEntry)
                    .outerjoin(
                        UsageEvent,
                        and_(
                            UsageEvent.id == CostEntry.usage_event_id,
                            UsageEvent.occurred_at >= lo - timedelta(days=1),
                            UsageEvent.occurred_at < hi + timedelta(days=1),
                        ),
                    )
                    .where(in_range)
                    .group_by(key_col)
                )
            elif group_by == "user":
                stmt = (
                    select(
                        func.coalesce(cast(CostEntry.user_id, String), "none"),
                        func.coalesce(User.email, "unattributed"),
                        total_usd,
                        func.count(),
                    )
                    .select_from(CostEntry)
                    .outerjoin(User, User.id == CostEntry.user_id)
                    .where(in_range)
                    .group_by(CostEntry.user_id, User.email)
                )
            else:
                col = {
                    "component": CostEntry.component,
                    "provider": CostEntry.provider,
                    "cost_center": CostEntry.cost_center,
                }[group_by]
                stmt = select(col, col, total_usd, func.count()).where(in_range).group_by(col)
            group_rows = (await s.execute(stmt.order_by(total_usd.desc()))).all()

            kind_rows = (
                await s.execute(
                    select(CostEntry.kind, total_usd).where(in_range).group_by(CostEntry.kind)
                )
            ).all()
            day = func.date(func.timezone("UTC", CostEntry.created_at))
            daily_rows = (
                await s.execute(select(day, total_usd).where(in_range).group_by(day).order_by(day))
            ).all()
            usage = (
                await s.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(UsageEvent.connected_seconds), 0),
                        func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                        func.coalesce(func.sum(UsageEvent.output_tokens), 0),
                        func.count().filter(
                            or_(
                                UsageEvent.input_tokens.is_not(None),
                                UsageEvent.output_tokens.is_not(None),
                            )
                        ),
                        func.coalesce(func.sum(UsageEvent.sandbox_seconds), 0),
                    ).where(UsageEvent.occurred_at >= lo, UsageEvent.occurred_at < hi)
                )
            ).one()

        def label(raw: Any) -> str:
            return str(raw.value if hasattr(raw, "value") else raw)

        groups = []
        for key, name, amount, n in group_rows:
            text_label = (
                mask_email(name) if group_by == "user" and "@" in str(name) else label(name)
            )
            groups.append(
                CostGroup(key=label(key), label=text_label, usd=usd(amount), entries=int(n))
            )
        by_kind = {label(k): usd(v) for k, v in kind_rows}
        total = round(sum(g.usd for g in groups), 6)
        reconciled = by_kind.get("reconciled", 0.0) + by_kind.get("provider", 0.0)
        return CostReport(
            start=start,
            end=end,
            group_by=group_by,
            total_usd=total,
            by_kind=by_kind,
            reconciled_share=round(reconciled / total, 4) if total else 0.0,
            groups=groups,
            daily=[DailyCost(day=d, usd=usd(v)) for d, v in daily_rows],
            usage=UsageTotals(
                events=int(usage[0]),
                connected_seconds=float(usage[1] or 0),
                input_tokens=int(usage[2] or 0),
                output_tokens=int(usage[3] or 0),
                token_reporting_events=int(usage[4]),
                sandbox_seconds=float(usage[5] or 0),
            ),
        )

    # ── calls ──
    async def _call_rows(
        self,
        s: AsyncSession,
        where: ColumnElement[bool],
        order: list[ColumnElement[Any]],
        limit: int,
    ) -> list[CallRow]:
        latest = (
            select(func.max(CallAttempt.attempt_no))
            .where(CallAttempt.occurrence_id == CallOccurrence.id)
            .correlate(CallOccurrence)
            .scalar_subquery()
        )
        rows = (
            await s.execute(
                select(CallOccurrence, CallAttempt, User.email)
                .outerjoin(
                    CallAttempt,
                    and_(
                        CallAttempt.occurrence_id == CallOccurrence.id,
                        CallAttempt.attempt_no == latest,
                    ),
                )
                .outerjoin(User, User.id == CallOccurrence.user_id)
                .where(where)
                .order_by(*order)
                .limit(limit)
            )
        ).all()
        out: list[CallRow] = []
        for occ, att, email in rows:
            out.append(
                CallRow(
                    occurrence_id=str(occ.id),
                    kind="test" if occ.is_test else "scheduled",
                    request_id=occ.request_id,
                    user_masked=mask_email(email) if email else None,
                    state=(att.state if att else occ.state).value,
                    channel=att.channel.value if att else None,
                    scheduled_for=occ.scheduled_for,
                    attempt_no=att.attempt_no if att else None,
                    el_conversation_id=att.el_conversation_id if att else None,
                    twilio_call_sid=att.twilio_call_sid if att else None,
                    error=(att.error[:MAX_ERROR_CHARS] if att and att.error else None),
                    ended_at=att.ended_at if att else None,
                )
            )
        return out

    async def calls(self, now: datetime) -> CallsReport:
        async with self._sessions() as s:
            upcoming = await self._call_rows(
                s,
                CallOccurrence.state.in_(UPCOMING_STATES),
                [CallOccurrence.scheduled_for.asc()],
                50,
            )
            active = await self._call_rows(
                s,
                CallOccurrence.state.in_(ACTIVE_STATES),
                [CallOccurrence.scheduled_for.desc()],
                50,
            )
            recent = await self._call_rows(
                s,
                CallOccurrence.state.not_in((*UPCOMING_STATES, *ACTIVE_STATES)),
                [CallOccurrence.scheduled_for.desc()],
                50,
            )
            counts = (
                await s.execute(
                    select(CallOccurrence.state, func.count())
                    .where(CallOccurrence.scheduled_for >= now - timedelta(days=7))
                    .group_by(CallOccurrence.state)
                )
            ).all()
        return CallsReport(
            generated_at=now,
            upcoming=upcoming,
            active=active,
            recent=recent,
            state_counts_7d={st.value: int(n) for st, n in counts},
        )

    async def agents(self, agent_ids: dict[str, str], now: datetime) -> list[AgentRow]:
        since = now - timedelta(days=30)
        async with self._sessions() as s:
            stats = {
                row[0]: row
                for row in (
                    await s.execute(
                        select(
                            VoiceSession.character,
                            func.count(),
                            func.count().filter(VoiceSession.status == SessionStatus.FAILED),
                            func.count().filter(VoiceSession.is_test.is_(True)),
                            func.avg(VoiceSession.duration_seconds),
                        )
                        .where(VoiceSession.created_at >= since)
                        .group_by(VoiceSession.character)
                    )
                ).all()
            }
            version_rows = (
                await s.execute(
                    select(VoiceSession.character, VoiceSession.agent_version)
                    .where(
                        VoiceSession.created_at >= since, VoiceSession.agent_version.is_not(None)
                    )
                    .distinct()
                )
            ).all()
        versions: dict[Character, list[str]] = {}
        for character, version in version_rows:
            versions.setdefault(character, []).append(str(version))
        out: list[AgentRow] = []
        for character in Character:
            row = stats.get(character)
            agent_id = agent_ids.get(character.value)
            out.append(
                AgentRow(
                    character=character.value,
                    agent_id=agent_id,
                    configured=bool(agent_id),
                    sessions_30d=int(row[1]) if row else 0,
                    failed_30d=int(row[2]) if row else 0,
                    test_sessions_30d=int(row[3]) if row else 0,
                    avg_duration_seconds=(
                        round(float(row[4]), 1) if row and row[4] is not None else None
                    ),
                    versions=sorted(versions.get(character, [])),
                )
            )
        return out

    # ── quality and operations ──
    async def quality(self, now: datetime) -> QualityReport:
        d7 = now - timedelta(days=7)
        async with self._sessions() as s:
            a_rows = (
                await s.execute(select(Assessment.status, func.count()).group_by(Assessment.status))
            ).all()
            by_status = {st.value: int(n) for st, n in a_rows}
            oldest_pending = await s.scalar(
                select(func.min(Assessment.created_at)).where(
                    Assessment.status == AssessmentStatus.PENDING
                )
            )
            d_rows = (
                await s.execute(
                    select(AssessmentDispute.status, func.count()).group_by(
                        AssessmentDispute.status
                    )
                )
            ).all()
            disputes = {st.value: int(n) for st, n in d_rows}
            e_rows = (
                await s.execute(
                    select(ProviderEvent.status, func.count()).group_by(ProviderEvent.status)
                )
            ).all()
            oldest_unprocessed = await s.scalar(
                select(func.min(ProviderEvent.received_at)).where(
                    ProviderEvent.status.in_(
                        (ProviderEventStatus.RECEIVED, ProviderEventStatus.ENQUEUED)
                    )
                )
            )
            latency = await s.scalar(
                select(
                    func.avg(
                        func.extract(
                            "epoch", ProviderEvent.processed_at - ProviderEvent.received_at
                        )
                    )
                ).where(
                    ProviderEvent.status == ProviderEventStatus.PROCESSED,
                    ProviderEvent.received_at >= now - timedelta(days=1),
                    ProviderEvent.processed_at.is_not(None),
                )
            )
            failed = (
                await s.scalars(
                    select(ProviderEvent)
                    .where(ProviderEvent.status == ProviderEventStatus.FAILED)
                    .order_by(ProviderEvent.received_at.desc())
                    .limit(10)
                )
            ).all()
            failed_sessions = await _one(
                s,
                select(func.count()).where(
                    VoiceSession.created_at >= d7, VoiceSession.status == SessionStatus.FAILED
                ),
                0,
            )
            interrupted = await _one(
                s,
                select(func.count()).where(
                    VoiceSession.created_at >= d7,
                    VoiceSession.status == SessionStatus.INTERRUPTED,
                ),
                0,
            )
        resolved = sum(n for st, n in disputes.items() if st != DisputeStatus.OPEN.value)
        upheld = disputes.get(DisputeStatus.UPHELD.value, 0)
        return QualityReport(
            generated_at=now,
            assessments_by_status=by_status,
            judge_backlog=by_status.get(AssessmentStatus.PENDING.value, 0),
            oldest_pending_assessment_age_s=(
                (now - oldest_pending).total_seconds() if oldest_pending else None
            ),
            open_disputes=disputes.get(DisputeStatus.OPEN.value, 0),
            resolved_disputes=resolved,
            disputes_upheld=upheld,
            disagreement_rate=round(upheld / resolved, 4) if resolved else None,
            provider_events_by_status={st.value: int(n) for st, n in e_rows},
            webhook_oldest_unprocessed_age_s=(
                (now - oldest_unprocessed).total_seconds() if oldest_unprocessed else None
            ),
            webhook_avg_latency_s_24h=round(float(latency), 3) if latency is not None else None,
            failed_events=[
                FailedEvent(
                    id=str(e.id),
                    provider=e.provider,
                    event_type=e.event_type,
                    attempts=e.attempts,
                    error=e.error[:MAX_ERROR_CHARS] if e.error else None,
                    received_at=e.received_at,
                )
                for e in failed
            ],
            failed_sessions_7d=failed_sessions,
            interrupted_sessions_7d=interrupted,
        )

    # ── audit ──
    async def audit(
        self,
        *,
        action_prefix: str | None,
        actor_email: str | None,
        before: datetime | None,
        limit: int,
    ) -> AuditPage:
        stmt = (
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(limit + 1)
        )
        if action_prefix:
            stmt = stmt.where(AuditLog.action.like(f"{escape_like(action_prefix)}%", escape="\\"))
        if actor_email:
            like = f"%{escape_like(actor_email.strip())}%"
            stmt = stmt.where(User.email.ilike(like, escape="\\"))
        if before:
            stmt = stmt.where(AuditLog.occurred_at < before)
        async with self._sessions() as s:
            rows = (await s.execute(stmt)).all()
        page = rows[:limit]
        items: list[AuditRow] = []
        for row, email in page:
            after = dict(row.after) if row.after else None
            meta = (after or {}).pop(AUDIT_META_KEY, None) or {}
            items.append(
                AuditRow(
                    id=str(row.id),
                    occurred_at=row.occurred_at,
                    actor_type=row.actor_type.value,
                    actor_email=email or meta.get("actor_email"),
                    action=row.action,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    request_id=row.request_id,
                    status_code=meta.get("status_code"),
                    before=row.before,
                    after=after or None,
                )
            )
        has_more = len(rows) > limit
        return AuditPage(
            items=items, next_before=items[-1].occurred_at if has_more and items else None
        )

    # ── Call now ──
    async def create_test_call(
        self,
        *,
        request_id: str,
        channel: CallChannelKind,
        estimate_usd: Decimal,
        budget_limit_usd: Decimal,
        cooldown_s: int,
        now: datetime,
    ) -> tuple[TestCallRecord, bool]:
        async with self._sessions() as s, s.begin():
            # One Call now at a time: serialises the replay check, the cooldown and the hold.
            await s.execute(select(func.pg_advisory_xact_lock(func.hashtext("admin:call_now"))))
            existing = await s.scalar(
                select(CallOccurrence).where(CallOccurrence.request_id == request_id)
            )
            if existing is not None:
                return await self._record_for(s, existing), False

            last = await s.scalar(
                select(func.max(CallOccurrence.created_at)).where(
                    CallOccurrence.is_test.is_(True), CallOccurrence.schedule_id.is_(None)
                )
            )
            if last is not None:
                wait = cooldown_s - (now - last).total_seconds()
                if wait > 0:
                    raise CooldownError(int(wait) + 1)

            occ = CallOccurrence(
                id=uuid.uuid4(),
                schedule_id=None,
                user_id=None,
                local_date=now.date(),
                scheduled_for=now,
                state=CallState.QUEUED,
                is_test=True,
                request_id=request_id,
                created_at=now,  # app clock, the same one the cooldown compares against
            )
            s.add(occ)
            await s.flush()
            await reserve(
                s,
                budget_key=budget_key_for(CostCenter.DEVELOPER, at=now),
                amount_usd=estimate_usd,
                limit_usd=budget_limit_usd,
                cost_center=CostCenter.DEVELOPER,
                call_occurrence_id=occ.id,
                now=now,
            )
            attempt = CallAttempt(
                id=uuid.uuid4(),
                occurrence_id=occ.id,
                attempt_no=1,
                channel=channel,
                state=CallState.QUEUED,
            )
            s.add(attempt)
            await s.flush()
            return (
                TestCallRecord(
                    occurrence_id=occ.id,
                    attempt_id=attempt.id,
                    request_id=request_id,
                    state=CallState.QUEUED,
                    channel=channel,
                    el_conversation_id=None,
                ),
                True,
            )

    @staticmethod
    async def _record_for(s: AsyncSession, occ: CallOccurrence) -> TestCallRecord:
        attempt = (
            await s.scalars(
                select(CallAttempt)
                .where(CallAttempt.occurrence_id == occ.id)
                .order_by(CallAttempt.attempt_no.desc())
                .limit(1)
            )
        ).first()
        if attempt is None:  # created by something that never made an attempt
            raise RuntimeError(f"occurrence {occ.id} has no attempt")
        return TestCallRecord(
            occurrence_id=occ.id,
            attempt_id=attempt.id,
            request_id=occ.request_id or "",
            state=attempt.state,
            channel=attempt.channel,
            el_conversation_id=attempt.el_conversation_id,
        )

    async def record_dispatch(
        self,
        record: TestCallRecord,
        *,
        state: CallState,
        el_conversation_id: str | None,
        twilio_call_sid: str | None,
        error: str | None,
        release_budget: bool,
    ) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as s, s.begin():
            occ = await s.get(CallOccurrence, record.occurrence_id, with_for_update=True)
            attempt = await s.get(CallAttempt, record.attempt_id, with_for_update=True)
            if occ is None or attempt is None:
                raise LookupError("call record vanished")
            occ.state = state
            attempt.state = state
            attempt.el_conversation_id = el_conversation_id
            attempt.twilio_call_sid = twilio_call_sid
            attempt.error = error
            if state is not CallState.FAILED:
                attempt.dispatched_at = now
            if release_budget:
                held = (
                    await s.scalars(
                        select(BudgetReservation).where(
                            BudgetReservation.call_occurrence_id == occ.id,
                            BudgetReservation.status == ReservationStatus.RESERVED,
                        )
                    )
                ).all()
                for hold in held:
                    await release(s, hold.id)
