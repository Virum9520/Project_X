"""Budget gate for assistant model turns (cost center `owner_assistant`)."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sg_core.economics.budget import Hold, budget_hold, budget_key_for, monthly_limit_usd
from sg_core.models.enums import CostCenter
from sg_core.settings import Settings


class AssistantBudget(Protocol):
    def hold(self, amount_usd: Decimal) -> AbstractAsyncContextManager[Hold]:
        """Reserve `amount_usd`; raises `BudgetExceededError`. Settles on exit at `actual_usd`
        (or the held amount), releases when the body raises before setting it."""
        ...


class DbAssistantBudget:
    """Holds against `owner_assistant:YYYY-MM` in `budget_reservations` (C03)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def hold(self, amount_usd: Decimal) -> AbstractAsyncContextManager[Hold]:
        return budget_hold(
            budget_key=budget_key_for(CostCenter.OWNER_ASSISTANT, at=datetime.now(UTC)),
            amount_usd=amount_usd,
            limit_usd=monthly_limit_usd(CostCenter.OWNER_ASSISTANT, self._settings),
            cost_center=CostCenter.OWNER_ASSISTANT,
        )
