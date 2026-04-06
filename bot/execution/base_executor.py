"""Base executor abstractions shared by execution modes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from bot.engine.risk_manager import RiskCheckResult
from bot.engine.signals import Candle
from bot.storage.models import BotState, EventRecord, FillRecord, InstrumentConstraints, OrderIntent, OrderRecord


@dataclass(slots=True)
class ExecutionResult:
    """Outcome of one executor step."""

    order: OrderRecord | None = None
    fills: list[FillRecord] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    updated_state: BotState | None = None
    risk_result: RiskCheckResult | None = None
    blocked: bool = False
    safe_stop_required: bool = False
    reason: str | None = None


class BaseExecutor(ABC):
    """Abstract executor interface for order-intent execution."""

    @abstractmethod
    async def execute_intent(
        self,
        intent: OrderIntent,
        state: BotState,
        candle: Candle,
        constraints: InstrumentConstraints,
        seen_intent_keys: set[str] | None = None,
    ) -> ExecutionResult:
        """Execute one normalized order intent."""
