"""Tests for startup and restore bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, EvenBarAnchorMode, LiveStartPolicy, Settings
from bot.data.market_stream import Candle
from bot.main import (
    build_dry_run_stack,
    build_initial_state,
    create_orchestrator,
    restore_or_initialize_state,
)
from bot.storage.models import BotState


@dataclass
class FakeStorage:
    """Minimal fake storage for startup and restore tests."""

    restored_state: BotState | None = None
    init_db_calls: int = 0
    load_calls: int = 0

    async def init_db(self) -> None:
        self.init_db_calls += 1

    async def load_bot_state(self, mode: BotMode, symbol: str, timeframe: str) -> BotState | None:
        self.load_calls += 1
        return self.restored_state

    async def save_bot_state(self, state: BotState) -> None:
        self.restored_state = state

    async def save_order(self, order) -> None:
        pass

    async def save_fill(self, fill) -> None:
        pass

    async def save_event(self, event) -> None:
        pass

    async def save_safe_stop_reason(self, record) -> None:
        pass


def _settings(policy: LiveStartPolicy) -> Settings:
    return Settings(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        live_start_policy=policy,
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
async def test_orchestrator_works_with_restored_state() -> None:
    restored = _restored_state()
    storage = FakeStorage(restored_state=restored)
    stack = await build_dry_run_stack(settings=_settings(LiveStartPolicy.RESTORE), storage=storage)

    await stack.orchestrator.process_candle_update(
        Candle(
            open_time=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
            close_time=datetime(2026, 4, 10, 12, 2, tzinfo=timezone.utc),
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=1.0,
        )
    )
    result = await stack.orchestrator.process_candle_update(
        Candle(
            open_time=datetime(2026, 4, 10, 12, 2, tzinfo=timezone.utc),
            close_time=datetime(2026, 4, 10, 12, 3, tzinfo=timezone.utc),
            open=101.0,
            high=106.0,
            low=100.0,
            close=105.0,
            volume=1.0,
        )
    )

    assert result.closed_bar_processed is True
    assert result.runtime_state is not None


@pytest.mark.asyncio
async def test_duplicate_old_update_after_restore_does_not_break_pipeline() -> None:
    restored = _restored_state()
    storage = FakeStorage(restored_state=restored)
    stack = await build_dry_run_stack(settings=_settings(LiveStartPolicy.RESTORE), storage=storage)

    old_update = Candle(
        open_time=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=1.0,
    )
    next_update = Candle(
        open_time=datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 10, 12, 2, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
    )

    first = await stack.orchestrator.process_candle_update(old_update)
    second = await stack.orchestrator.process_candle_update(next_update)

    assert first.closed_bar_processed is False
    assert second.closed_bar_processed is False


@pytest.mark.asyncio
async def test_safe_stop_state_is_restored_as_is() -> None:
    restored = _restored_state()
    restored.safe_stop_active = True
    restored.safe_stop_reason = "manual safe stop"
    storage = FakeStorage(restored_state=restored)

    state = await restore_or_initialize_state(settings=_settings(LiveStartPolicy.RESTORE), storage=storage)

    assert state.safe_stop_active is True
    assert state.safe_stop_reason == "manual safe stop"


@pytest.mark.asyncio
async def test_bootstrap_does_not_require_network_calls() -> None:
    storage = FakeStorage()
    stack = await build_dry_run_stack(settings=_settings(LiveStartPolicy.RESET), storage=storage)

    assert stack.settings.mode == BotMode.DRY_RUN
    assert stack.runtime_state.symbol == "BTC-USDT"
    assert storage.init_db_calls == 1
