"""Tests for the pure risk manager."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.config import BotMode, Settings
from bot.engine.risk_manager import RiskManager
from bot.engine.signals import Candle
from bot.storage.models import BotState, OrderIntent, OrderIntentType, OrderSide


def _candle() -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=10.0,
    )


def _intent(intent_type: OrderIntentType) -> OrderIntent:
    return OrderIntent(
        intent_id=f"{intent_type.value}:2026-04-09T12:01:00+00:00",
        symbol="BTC-USDT",
        side=OrderSide.SELL if intent_type != OrderIntentType.SUB_COVER else OrderSide.BUY,
        intent_type=intent_type,
        qty=0.1,
        price=100.0,
        reason="test",
        created_at=datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc),
        cycle_id=1,
    )


def _state() -> BotState:
    return BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")


def test_limit_orders_per_3min() -> None:
    settings = Settings(max_orders_per_3min=2)
    manager = RiskManager(settings)
    state = _state()
    close_time = _candle().close_time
    state.orders_last_3min = [close_time - timedelta(minutes=2), close_time - timedelta(minutes=1)]

    result = manager.check_intent(state=state, intent=_intent(OrderIntentType.DCA_SHORT), candle=_candle())

    assert result.allow is False
    assert "3 minutes" in (result.reason or "")


def test_limit_dca_per_bar() -> None:
    settings = Settings(max_dca_per_bar=1)
    manager = RiskManager(settings)
    state = _state()
    state.fills_this_bar = 1

    result = manager.check_intent(state=state, intent=_intent(OrderIntentType.DCA_SHORT), candle=_candle())

    assert result.allow is False
    assert "DCA" in (result.reason or "")


def test_limit_subcover_per_bar() -> None:
    settings = Settings(max_subcover_per_bar=1)
    manager = RiskManager(settings)
    state = _state()
    state.subcovers_this_bar = 1

    result = manager.check_intent(state=state, intent=_intent(OrderIntentType.SUB_COVER), candle=_candle())

    assert result.allow is False
    assert "sub-cover" in (result.reason or "")


def test_blocked_by_safe_stop() -> None:
    manager = RiskManager(Settings())
    state = _state()
    state.safe_stop_active = True

    result = manager.check_intent(state=state, intent=_intent(OrderIntentType.FIRST_SHORT), candle=_candle())

    assert result.allow is False
    assert "safe_stop" in (result.reason or "")


def test_duplicate_guard_blocks_same_intent() -> None:
    manager = RiskManager(Settings())
    intent = _intent(OrderIntentType.FIRST_SHORT)

    result = manager.check_intent(
        state=_state(),
        intent=intent,
        candle=_candle(),
        seen_intent_keys={intent.intent_id},
    )

    assert result.allow is False
    assert "duplicate" in (result.reason or "")


def test_invalid_state_requires_safe_stop() -> None:
    manager = RiskManager(Settings())
    state = BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=1.0,
        avg_price=100.0,
        lots=[],
    )

    result = manager.check_intent(state=state, intent=_intent(OrderIntentType.DCA_SHORT), candle=_candle())

    assert result.allow is False
    assert result.safe_stop_required is True
