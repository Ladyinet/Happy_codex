"""Base executor abstractions shared by execution modes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bot.storage.models import BotState, ExecutionResult, InstrumentConstraints, OrderIntent


class BaseExecutor(ABC):
    """Abstract executor interface for order-intent execution."""

    @abstractmethod
    async def execute(
        self,
        intent: OrderIntent,
        state: BotState,
        constraints: InstrumentConstraints,
    ) -> ExecutionResult:
        """Execute one normalized order intent."""
