"""Tests for the dry-run executor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.config import BotMode, InvalidOrderPolicy, Settings
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.signals import Candle
from bot.execution.dry_run_executor import DryRunExecutor
from bot.execution.order_manager import OrderManager
from bot.storage.models import BotState, InstrumentConstraints, OrderIntent, OrderIntentType, OrderSide
from bot.utils.rounding import OrderNormalizer


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


def _candle(close: float) -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc),
        open=close - 1,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10.0,
    )


def _state() -> BotState:
    return BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")


def _intent(intent_type: OrderIntentType, *, side: OrderSide, qty: float, price: float) -> OrderIntent:
    return OrderIntent(
        intent_id=f"{intent_type.value}:1",
        symbol="BTC-USDT",
        side=side,
        intent_type=intent_type,
        qty=qty,
        price=price,
        reason="test",
        created_at=datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc),
        cycle_id=1,
    )


def _executor(settings: Settings) -> DryRunExecutor:
    return DryRunExecutor(
        risk_manager=RiskManager(settings),
        order_manager=OrderManager(),
        position_manager=PositionManager(),
        order_normalizer=OrderNormalizer(settings.invalid_order_policy),
    )


@pytest.mark.asyncio
async def test_valid_first_short_intent_creates_virtual_fill() -> None:
    executor = _executor(Settings())

    result = await executor.execute_intent(
        _intent(OrderIntentType.FIRST_SHORT, side=OrderSide.SELL, qty=0.1, price=100.0),
        _state(),
        _candle(100.0),
        _constraints(),
    )

    assert result.order is not None
    assert len(result.fills) == 1
    assert result.updated_state is not None
    assert result.updated_state.pos_size_abs == 0.1


@pytest.mark.asyncio
async def test_dca_intent_updates_state() -> None:
    executor = _executor(Settings())
    state = PositionManager().add_short_lot(
        _state(),
        qty=0.1,
        entry_price=100.0,
        tag="FIRST_SHORT",
        created_at=datetime(2026, 4, 9, 11, 59, tzinfo=timezone.utc),
        lot_id="lot_1",
        next_level_price=105.0,
    )

    result = await executor.execute_intent(
        _intent(OrderIntentType.DCA_SHORT, side=OrderSide.SELL, qty=0.1, price=106.0),
        state,
        _candle(106.0),
        _constraints(),
    )

    assert result.updated_state is not None
    assert result.updated_state.pos_size_abs > state.pos_size_abs


@pytest.mark.asyncio
async def test_full_cover_intent_resets_state() -> None:
    executor = _executor(Settings())
    state = PositionManager().add_short_lot(
        _state(),
        qty=0.1,
        entry_price=100.0,
        tag="FIRST_SHORT",
        created_at=datetime(2026, 4, 9, 11, 59, tzinfo=timezone.utc),
        lot_id="lot_1",
    )

    result = await executor.execute_intent(
        _intent(OrderIntentType.FULL_COVER, side=OrderSide.BUY, qty=0.1, price=99.0),
        state,
        _candle(99.0),
        _constraints(),
    )

    assert result.updated_state is not None
    assert result.updated_state.pos_size_abs == 0.0
    assert result.updated_state.reset_cycle is True


@pytest.mark.asyncio
async def test_blocked_risk_check_produces_no_fill() -> None:
    settings = Settings(max_orders_per_3min=0)
    executor = _executor(settings)

    result = await executor.execute_intent(
        _intent(OrderIntentType.FIRST_SHORT, side=OrderSide.SELL, qty=0.1, price=100.0),
        _state(),
        _candle(100.0),
        _constraints(),
    )

    assert result.blocked is True
    assert result.fills == []


@pytest.mark.asyncio
async def test_invalid_normalized_order_produces_no_fill() -> None:
    executor = _executor(Settings(invalid_order_policy=InvalidOrderPolicy.SKIP))

    result = await executor.execute_intent(
        _intent(OrderIntentType.FIRST_SHORT, side=OrderSide.SELL, qty=0.001, price=100.0),
        _state(),
        _candle(100.0),
        _constraints(),
    )

    assert result.blocked is True
    assert result.fills == []


@pytest.mark.asyncio
async def test_safe_stop_required_is_propagated() -> None:
    executor = _executor(Settings())
    invalid_state = BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m", pos_size_abs=1.0, lots=[])

    result = await executor.execute_intent(
        _intent(OrderIntentType.DCA_SHORT, side=OrderSide.SELL, qty=0.1, price=106.0),
        invalid_state,
        _candle(106.0),
        _constraints(),
    )

    assert result.safe_stop_required is True


@pytest.mark.asyncio
async def test_executor_returns_order_fill_and_updated_state() -> None:
    executor = _executor(Settings())

    result = await executor.execute_intent(
        _intent(OrderIntentType.FIRST_SHORT, side=OrderSide.SELL, qty=0.1, price=100.0),
        _state(),
        _candle(100.0),
        _constraints(),
    )

    assert result.order is not None
    assert result.fills
    assert result.updated_state is not None


@pytest.mark.asyncio
async def test_close_only_execution_uses_close_price() -> None:
    executor = _executor(Settings())
    candle = _candle(123.45)

    result = await executor.execute_intent(
        _intent(OrderIntentType.FIRST_SHORT, side=OrderSide.SELL, qty=0.1, price=120.0),
        _state(),
        candle,
        _constraints(),
    )

    assert result.fills[0].price == candle.close
