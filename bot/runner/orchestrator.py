"""End-to-end dry_run orchestration for the local v1 pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Protocol

from bot.data.candle_clock import CandleClock
from bot.data.market_stream import Candle as StreamCandle
from bot.data.market_stream import CandleUpdateBuffer, MarketUpdateResult
from bot.engine.signals import Candle as StrategyCandle
from bot.engine.signals import StrategyContext, StrategyDecision
from bot.engine.strategy_engine import StrategyEngine
from bot.execution.base_executor import ExecutionResult
from bot.execution.dry_run_executor import DryRunExecutor
from bot.storage.models import BotState, InstrumentConstraints, SafeStopRecord
from bot.utils.ids import new_id


class StorageProtocol(Protocol):
    """Minimal storage API required by the orchestrator."""

    async def save_bot_state(self, state: BotState) -> None:
        """Persist the current runtime state."""

    async def save_order(self, order) -> None:
        """Persist one order record."""

    async def save_fill(self, fill) -> None:
        """Persist one fill record."""

    async def save_event(self, event) -> None:
        """Persist one event record."""

    async def save_safe_stop_reason(self, record: SafeStopRecord) -> None:
        """Persist one safe-stop record."""


@dataclass(slots=True)
class OrchestratorStepResult:
    """Structured result of processing one candle update."""

    market_update: MarketUpdateResult
    closed_bar_processed: bool = False
    strategy_decision: StrategyDecision | None = None
    execution_results: list[ExecutionResult] = field(default_factory=list)
    runtime_state: BotState | None = None
    even_bar_allowed: bool | None = None


class DryRunOrchestrator:
    """Coordinates the local dry_run pipeline for one symbol and timeframe."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        runtime_state: BotState,
        storage: StorageProtocol,
        candle_buffer: CandleUpdateBuffer,
        candle_clock: CandleClock,
        strategy_engine: StrategyEngine,
        executor: DryRunExecutor,
        constraints: InstrumentConstraints,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.runtime_state = runtime_state
        self.storage = storage
        self.candle_buffer = candle_buffer
        self.candle_clock = candle_clock
        self.strategy_engine = strategy_engine
        self.executor = executor
        self.constraints = constraints
        self._last_processed_close_time = runtime_state.last_candle_time

    async def warmup_from_candles(self, candles: list[StreamCandle], *, persist_state: bool = True) -> int:
        """Preload historical candles into the buffer without retroactive strategy execution."""

        if not candles:
            return 0

        ordered = sorted(candles, key=lambda candle: candle.close_time)
        for candle in ordered:
            self.candle_buffer.process_update(candle)

        updated_state = deepcopy(self.runtime_state)
        updated_state.last_candle_time = ordered[-1].close_time
        self.runtime_state = updated_state
        self._last_processed_close_time = self.candle_buffer.last_emitted_close_time

        if persist_state:
            await self.storage.save_bot_state(self.runtime_state)

        return len(ordered)

    async def process_candle_update(self, candle_update: StreamCandle) -> OrchestratorStepResult:
        """Process one candle update through the local dry_run pipeline."""

        market_update = self.candle_buffer.process_update(candle_update)
        result = OrchestratorStepResult(market_update=market_update, runtime_state=self.runtime_state)

        if not market_update.emitted_new_closed_bar or market_update.closed_candle is None:
            return result

        closed_bar = market_update.closed_candle
        if self._last_processed_close_time is not None and closed_bar.close_time <= self._last_processed_close_time:
            return result

        even_bar_allowed = self.candle_clock.is_bar_allowed(closed_bar.close_time)
        strategy_candle = self._to_strategy_candle(closed_bar)
        decision = self.strategy_engine.evaluate_bar(
            StrategyContext(
                candle=strategy_candle,
                state=self.runtime_state,
                settings=self.executor.risk_manager.settings,
                even_bar_allowed=even_bar_allowed,
            )
        )

        result.closed_bar_processed = True
        result.strategy_decision = decision
        result.even_bar_allowed = even_bar_allowed

        if decision.safe_stop_required:
            if decision.updated_state is not None:
                self.runtime_state = decision.updated_state
                await self.storage.save_bot_state(self.runtime_state)
            for event in decision.events:
                await self.storage.save_event(event)
            await self.storage.save_safe_stop_reason(
                SafeStopRecord(
                    safe_stop_id=new_id("safe_stop"),
                    mode=self.runtime_state.mode,
                    symbol=self.runtime_state.symbol,
                    timeframe=self.runtime_state.timeframe,
                    reason=decision.safe_stop_reason or "strategy requested safe_stop",
                    created_at=closed_bar.close_time,
                )
            )
            self._last_processed_close_time = closed_bar.close_time
            result.runtime_state = self.runtime_state
            return result

        if not decision.order_intents:
            if decision.updated_state is not None:
                self.runtime_state = decision.updated_state
                await self.storage.save_bot_state(self.runtime_state)
            for event in decision.events:
                await self.storage.save_event(event)
            self._last_processed_close_time = closed_bar.close_time
            result.runtime_state = self.runtime_state
            return result

        seen_intent_keys: set[str] = set()
        working_state = self.runtime_state
        for intent in decision.order_intents:
            execution_result = await self.executor.execute_intent(
                intent=intent,
                state=working_state,
                candle=strategy_candle,
                constraints=self.constraints,
                seen_intent_keys=seen_intent_keys,
            )
            seen_intent_keys.add(intent.intent_id)
            result.execution_results.append(execution_result)

            if execution_result.updated_state is not None:
                working_state = execution_result.updated_state
                await self.storage.save_bot_state(working_state)
            if execution_result.order is not None:
                await self.storage.save_order(execution_result.order)
            for fill in execution_result.fills:
                await self.storage.save_fill(fill)
            for event in execution_result.events:
                await self.storage.save_event(event)
            if execution_result.safe_stop_required:
                await self.storage.save_safe_stop_reason(
                    SafeStopRecord(
                        safe_stop_id=new_id("safe_stop"),
                        mode=working_state.mode,
                        symbol=working_state.symbol,
                        timeframe=working_state.timeframe,
                        reason=execution_result.reason or "executor requested safe_stop",
                        created_at=closed_bar.close_time,
                    )
                )

        self.runtime_state = working_state
        self._last_processed_close_time = closed_bar.close_time
        result.runtime_state = self.runtime_state
        return result

    @staticmethod
    def _to_strategy_candle(candle: StreamCandle) -> StrategyCandle:
        """Convert market-stream candle model into strategy candle model."""

        return StrategyCandle(
            open_time=candle.open_time,
            close_time=candle.close_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            is_closed=True,
        )
