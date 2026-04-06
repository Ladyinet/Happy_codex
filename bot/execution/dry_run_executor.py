"""Dry-run executor skeleton using local virtual execution only."""

from __future__ import annotations

from bot.execution.base_executor import BaseExecutor
from bot.storage.models import BotState, ExecutionResult, InstrumentConstraints, OrderIntent


class DryRunExecutor(BaseExecutor):
    """Executes normalized intents against local virtual state without exchange orders."""

    async def execute(
        self,
        intent: OrderIntent,
        state: BotState,
        constraints: InstrumentConstraints,
    ) -> ExecutionResult:
        """Simulate execution using the same shared normalization path as future live mode."""
        raise NotImplementedError
