"""Tests for the dry_run orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, EvenBarAnchorMode, Settings
from bot.data.candle_clock import CandleClock
from bot.data.market_stream import Candle, CandleUpdateBuffer
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.execution.dry_run_executor import DryRunExecutor
from bot.execution.order_manager import OrderManager
from bot.runner.orchestrator import DryRunOrchestrator
from bot.storage.models import BotState, InstrumentConstraints, SafeStopRecord
from bot.utils.rounding import OrderNormalizer


@dataclass
class InMemoryStorage:
    """Simple in-memory storage spy for orchestrator tests."""

    states: list[BotState] = field(default_factory=list)
    orders: list[object] = field(default_factory=list)
    fills: list[object] = field(default_factory=list)
    events: list[object] = field(default_factory=list)
    safe_stops: list[SafeStopRecord] = field(default_factory=list)

    async def save_bot_state(self, state: BotState) -> None:
        self.states.append(state)

    async def save_order(self, order) -> None:
        self.orders.append(order)

    async def save_fill(self, fill) -> None:
        self.fills.append(fill)

    async def save_event(self, event) -> None:
        self.events.append(event)

    async def save_safe_stop_reason(self, record: SafeStopRecord) -> None:
        self.safe_stops.append(record)


def _constraints() -> InstrumentConstraints:
    return InstrumentConstraints(
        symbol="BTC-USDT",
        tick_size=0.1,
        lot_step=0.001,
        min_qty=0.01,
        min_notional=10.0,
        price_precision=1,
        qty_precision=3,
    )


def _candle(open_minute: int, close_minute: int, close: float) -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 10, 12, open_minute, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 10, 12, close_minute, tzinfo=timezone.utc),
        open=close - 1,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
    )


def _orchestrator(
    *,
    storage: InMemoryStorage | None = None,
    state: BotState | None = None,
    settings: Settings | None = None,
    clock: CandleClock | None = None,
) -> DryRunOrchestrator:
    storage = storage or InMemoryStorage()
    settings = settings or Settings()
    runtime_state = state or BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")
    return DryRunOrchestrator(
        symbol="BTC-USDT",
        timeframe="1m",
        runtime_state=runtime_state,
        storage=storage,
        candle_buffer=CandleUpdateBuffer(),
        candle_clock=clock or CandleClock(
            timeframe="1m",
            anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
            fixed_timestamp=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
        ),
        strategy_engine=StrategyEngine(),
        executor=DryRunExecutor(
            risk_manager=RiskManager(settings),
            order_manager=OrderManager(),
            position_manager=PositionManager(),
            order_normalizer=OrderNormalizer(settings.invalid_order_policy),
        ),
        constraints=_constraints(),
    )


@pytest.mark.asyncio
async def test_first_update_does_not_create_closed_bar_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    result = await orchestrator.process_candle_update(_candle(0, 1, 100.0))

    assert result.closed_bar_processed is False
    assert storage.orders == []
    assert storage.fills == []


@pytest.mark.asyncio
async def test_next_bar_closes_previous_and_runs_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.process_candle_update(_candle(0, 1, 100.0))
    result = await orchestrator.process_candle_update(_candle(1, 2, 101.0))

    assert result.closed_bar_processed is True
    assert len(storage.orders) == 1
    assert len(storage.fills) == 1
    assert len(storage.states) >= 1


@pytest.mark.asyncio
async def test_execution_result_is_saved_to_storage() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.process_candle_update(_candle(0, 1, 100.0))
    await orchestrator.process_candle_update(_candle(1, 2, 101.0))

    assert storage.orders
    assert storage.fills
    assert storage.events
    assert storage.states


@pytest.mark.asyncio
async def test_blocked_noop_scenario_does_not_break_pipeline() -> None:
    storage = InMemoryStorage()
    clock = CandleClock(
        timeframe="1m",
        anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
        fixed_timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
    )
    orchestrator = _orchestrator(storage=storage, clock=clock)

    await orchestrator.process_candle_update(_candle(0, 1, 100.0))
    result = await orchestrator.process_candle_update(_candle(1, 2, 101.0))

    assert result.closed_bar_processed is True
    assert result.execution_results == []
    assert storage.orders == []


@pytest.mark.asyncio
async def test_safe_stop_reason_is_saved() -> None:
    storage = InMemoryStorage()
    invalid_state = BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=1.0,
        lots=[],
    )
    orchestrator = _orchestrator(storage=storage, state=invalid_state)

    await orchestrator.process_candle_update(_candle(0, 1, 100.0))
    result = await orchestrator.process_candle_update(_candle(1, 2, 101.0))

    assert result.strategy_decision is not None
    assert result.strategy_decision.safe_stop_required is True
    assert len(storage.safe_stops) == 1


@pytest.mark.asyncio
async def test_runtime_state_updates_after_successful_fill() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.process_candle_update(_candle(0, 1, 100.0))
    result = await orchestrator.process_candle_update(_candle(1, 2, 101.0))

    assert result.runtime_state is not None
    assert result.runtime_state.pos_size_abs > 0


@pytest.mark.asyncio
async def test_duplicate_or_old_candle_update_does_not_repeat_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    first = _candle(0, 1, 100.0)
    second = _candle(1, 2, 101.0)
    old = _candle(0, 1, 99.0)

    await orchestrator.process_candle_update(first)
    await orchestrator.process_candle_update(second)
    order_count = len(storage.orders)

    duplicate_result = await orchestrator.process_candle_update(second)
    old_result = await orchestrator.process_candle_update(old)

    assert len(storage.orders) == order_count
    assert duplicate_result.closed_bar_processed is False
    assert old_result.closed_bar_processed is False


@pytest.mark.asyncio
async def test_warmup_does_not_create_retroactive_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    loaded = await orchestrator.warmup_from_candles(
        [
            _candle(0, 1, 100.0),
            _candle(1, 2, 101.0),
            _candle(2, 3, 102.0),
        ]
    )

    assert loaded == 3
    assert storage.orders == []
    assert storage.fills == []
    assert storage.events == []
    assert orchestrator.runtime_state.last_candle_time == datetime(2026, 4, 10, 12, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_duplicate_already_known_candle_after_warmup_does_not_run_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.warmup_from_candles(
        [
            _candle(0, 1, 100.0),
            _candle(1, 2, 101.0),
        ]
    )
    result = await orchestrator.process_candle_update(_candle(1, 2, 101.5))

    assert result.closed_bar_processed is False
    assert storage.orders == []
    assert storage.fills == []


@pytest.mark.asyncio
async def test_next_new_bar_after_warmup_runs_one_execution_path() -> None:
    storage = InMemoryStorage()
    clock = CandleClock(
        timeframe="1m",
        anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
        fixed_timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
    )
    orchestrator = _orchestrator(storage=storage, clock=clock)

    await orchestrator.warmup_from_candles(
        [
            _candle(0, 1, 100.0),
            _candle(1, 2, 101.0),
        ]
    )
    result = await orchestrator.process_candle_update(_candle(2, 3, 102.0))

    assert result.closed_bar_processed is True
    assert len(result.execution_results) == 1
    assert len(storage.orders) == 1
    assert len(storage.fills) == 1
