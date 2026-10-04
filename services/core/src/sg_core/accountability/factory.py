"""Production wiring for the accountability services (API routes and the worker share it)."""

from sg_core.accountability.budget import DbBudgetGuard
from sg_core.accountability.channels import (
    CallChannel,
    PhoneCallChannel,
    WebCallChannel,
    push_sender_from_settings,
)
from sg_core.accountability.db_store import DbAccountabilityStore
from sg_core.accountability.dispatcher import CallDispatcher, DispatchPolicy, policy_from_settings
from sg_core.accountability.store import AccountabilityStore
from sg_core.db import get_sessionmaker
from sg_core.models.enums import CallChannelKind
from sg_core.settings import Settings


def build_dispatcher(
    store: AccountabilityStore, settings: Settings, policy: DispatchPolicy | None = None
) -> CallDispatcher:
    policy = policy or policy_from_settings(settings)
    channels: dict[CallChannelKind, CallChannel] = {
        CallChannelKind.WEB: WebCallChannel(
            store,
            push_sender_from_settings(settings),
            ring_timeout_seconds=int(policy.ring_timeout.total_seconds()),
        ),
        CallChannelKind.PHONE: PhoneCallChannel(),
    }
    return CallDispatcher(store, DbBudgetGuard(get_sessionmaker(), settings), channels, policy)


def db_store() -> AccountabilityStore:
    return DbAccountabilityStore(get_sessionmaker())
