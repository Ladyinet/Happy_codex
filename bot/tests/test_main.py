"""Tests for startup, restore, and read-only backfill bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, EvenBarAnchorMode, LiveStartPolicy, Settings
from bot.data.market_stream import Candle
from bot.main import BootstrapError, build_dry_run_stack, restore_or_initialize_state
from bot.storage.models import BotState, InstrumentConstraints


@dataclass
class FakeStorage:
    """Minimal fake storage for startup and restore tests."""

    restored_state: BotState | None = None
    init_db_calls: int = 0
    load_calls: int = 0
    states: list[BotState] | None = None

    def __post_init__(self) -> None:
        if self.states is None:
            self.states = []

    async def init_db(self) -> None:
        self.init_db_calls += 1

    async def load_bot_state(self, mode: BotMode, symbol: str, timeframe: str) -> BotState | None:
        self.load_calls += 1
        return self.restored_state

    async def save_bot_state(self, state: BotState) -> None:
        self.restored_state = state
        self.states.append(state)

    async def save_order(self, order) -> None:
        pass

    async def save_fill(self, fill) -> None:
        pass

    async def save_event(self, event) -> None:
        pass

    async def save_safe_stop_reason(self, record) -> None:
        pass


class FakeMarketSource:
    """Simple fake read-only market source for bootstrap tests."""

    def __init__(
        self,
        *,
        constraints: InstrumentConstraints | None = None,
        candles: list[Candle] | None = None,
        constraints_error: Exception | None = None,
        candles_error: Exception | None = None,
    ) -> None:
        self.constraints = constraints or InstrumentConstraints(
            symbol="BTC-USDT",
            tick_size=0.1,
            lot_step=0.0001,
            min_qty=0.0001,
            min_notional=2.0,
            price_precision=1,
            qty_precision=4,
        )
        self.candles = candles or []
        self.constraints_error = constraints_error
        self.candles_error = candles_error
        self.constraints_calls = 0
        self.candles_calls = 0

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        self.constraints_calls += 1
        if self.constraints_error is not None:
            raise self.constraints_error
        return self.constraints

    async def fetch_startup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.candles_calls += 1
        if self.candles_error is not None:
            raise self.candles_error
        return list(self.candles)[-limit:]


def _settings(policy: LiveStartPolicy) -> Settings:
    return Settings(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        live_start_policy=policy,
        startup_candles_backfill=5,
        even_bar_anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
        even_bar_fixed_timestamp="2026-04-10T12:01:00+00:00",
    )


def _restored_state() -> BotState:
    return BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=0.2,
        pos_proceeds_usdt=20.0,
        avg_price=100.0,
        last_candle_time=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
        safe_stop_active=False,
    )


def _startup_candle(open_minute: int, close_minute: int, close: float) -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 10, 12, open_minute, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 10, 12, close_minute, tzinfo=timezone.utc),
        open=close - 1,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
        is_closed=True,
    )


@pytest.mark.asyncio
async def test_reset_policy_builds_clean_initial_state() -> None:
    storage = FakeStorage(restored_state=_restored_state())
    state = await restore_or_initialize_state(settings=_settings(LiveStartPolicy.RESET), storage=storage)

    assert state.pos_size_abs == 0.0
    assert state.symbol == "BTC-USDT"
    assert storage.load_calls == 0


@pytest.mark.asyncio
async def test_restore_policy_uses_existing_saved_state() -> None:
    restored = _restored_state()
    storage = FakeStorage(restored_state=restored)

    state = await restore_or_initialize_state(settings=_settings(LiveStartPolicy.RESTORE), storage=storage)

    assert state is restored
    assert state.pos_size_abs == 0.2
    assert storage.load_calls == 1


@pytest.mark.asyncio
async def test_restore_policy_without_saved_state_builds_clean_state() -> None:
    storage = FakeStorage(restored_state=None)

    state = await restore_or_initialize_state(settings=_settings(LiveStartPolicy.RESTORE), storage=storage)

    assert state.pos_size_abs == 0.0
    assert state.last_candle_time is None
    assert storage.load_calls == 1


@pytest.mark.asyncio
async def test_bootstrap_fetches_constraints_and_startup_candles_successfully() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource(
        candles=[
            _startup_candle(0, 1, 100.0),
            _startup_candle(1, 2, 101.0),
        ]
    )

    stack = await build_dry_run_stack(
        settings=_settings(LiveStartPolicy.RESET),
        storage=storage,
        market_source=market_source,
    )

    assert market_source.constraints_calls == 1
    assert market_source.candles_calls == 1
    assert stack.constraints.symbol == "BTC-USDT"
    assert stack.startup_candles_loaded == 2
    assert stack.runtime_state.last_candle_time == datetime(2026, 4, 10, 12, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_restore_bootstrap_works_with_restored_state_and_backfill() -> None:
    restored = _restored_state()
    storage = FakeStorage(restored_state=restored)
    market_source = FakeMarketSource(
        candles=[
            _startup_candle(1, 2, 100.5),
            _startup_candle(2, 3, 101.0),
        ]
    )

    stack = await build_dry_run_stack(
        settings=_settings(LiveStartPolicy.RESTORE),
        storage=storage,
        market_source=market_source,
    )

    assert stack.runtime_state.pos_size_abs == 0.2
    assert stack.runtime_state.last_candle_time == datetime(2026, 4, 10, 12, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_safe_stop_state_is_restored_as_is() -> None:
    restored = _restored_state()
    restored.safe_stop_active = True
    restored.safe_stop_reason = "manual safe stop"
    storage = FakeStorage(restored_state=restored)
    market_source = FakeMarketSource(candles=[_startup_candle(1, 2, 100.5)])

    stack = await build_dry_run_stack(
        settings=_settings(LiveStartPolicy.RESTORE),
        storage=storage,
        market_source=market_source,
    )

    assert stack.runtime_state.safe_stop_active is True
    assert stack.runtime_state.safe_stop_reason == "manual safe stop"


@pytest.mark.asyncio
async def test_bootstrap_raises_clear_error_when_metadata_fetch_fails() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource(constraints_error=RuntimeError("metadata boom"))

    with pytest.raises(BootstrapError, match="Failed to fetch instrument constraints"):
        await build_dry_run_stack(
            settings=_settings(LiveStartPolicy.RESET),
            storage=storage,
            market_source=market_source,
        )


@pytest.mark.asyncio
async def test_empty_startup_candles_start_with_clean_buffer() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource(candles=[])

    stack = await build_dry_run_stack(
        settings=_settings(LiveStartPolicy.RESET),
        storage=storage,
        market_source=market_source,
    )

    assert stack.startup_candles_loaded == 0
    assert stack.runtime_state.last_candle_time is None
    assert stack.buffer.current_candle is None


@pytest.mark.asyncio
async def test_bootstrap_does_not_require_real_network_when_market_source_is_injected() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource(candles=[_startup_candle(0, 1, 100.0)])

    stack = await build_dry_run_stack(
        settings=_settings(LiveStartPolicy.RESET),
        storage=storage,
        market_source=market_source,
    )

    assert stack.settings.mode == BotMode.DRY_RUN
    assert stack.runtime_state.symbol == "BTC-USDT"
    assert storage.init_db_calls == 1
