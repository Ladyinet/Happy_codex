"""Tests for the pure strategy engine."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.config import BotMode, Settings, SubcoverConfirmMode, TouchMode
from bot.engine.position_manager import PositionManager
from bot.engine.signals import Candle, StrategyContext
from bot.engine.strategy_engine import StrategyEngine
from bot.storage.models import BotState, OrderIntent


def _candle(*, open: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 8, 12, 1, tzinfo=timezone.utc),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=10.0,
    )


def _empty_state() -> BotState:
    return BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")


def _position_state(num_sells: int = 1) -> BotState:
    manager = PositionManager()
    state = _empty_state()
    state = manager.add_short_lot(
        state,
        qty=0.1,
        entry_price=100.0,
        tag="FIRST_SHORT",
        created_at=datetime(2026, 4, 8, 11, 59, tzinfo=timezone.utc),
        lot_id="lot_1",
        next_level_price=105.0,
    )
    state.num_sells = num_sells
    return state


def test_full_tp_has_priority_over_dca_on_same_bar() -> None:
    engine = StrategyEngine()
    state = _position_state()
    settings = Settings(tp_percent=1.1, require_close_below_full_tp=True, touch_mode=TouchMode.WICK)
    candle = _candle(open=101.0, high=106.0, low=98.0, close=98.5)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=settings, even_bar_allowed=True))

    assert decision.full_tp_triggered is True
    assert decision.dca_triggered is False
    assert decision.order_intents[0].intent_type.value == "full_cover"


def test_full_tp_has_priority_over_subcover_on_same_bar() -> None:
    engine = StrategyEngine()
    manager = PositionManager()
    state = _position_state(num_sells=6)
    state = manager.add_short_lot(
        state,
        qty=0.1,
        entry_price=101.0,
        tag="DCA_6",
        created_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        lot_id="lot_2",
        next_level_price=105.0,
    )
    candle = _candle(open=102.0, high=103.0, low=97.0, close=98.0)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=Settings(), even_bar_allowed=True))

    assert decision.full_tp_triggered is True
    assert decision.subcover_triggered is False


def test_tp_touch_without_close_confirmation_does_not_full_tp() -> None:
    engine = StrategyEngine()
    state = _position_state()
    candle = _candle(open=100.5, high=104.0, low=98.0, close=99.5)
    settings = Settings(require_close_below_full_tp=True, touch_mode=TouchMode.WICK)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=settings, even_bar_allowed=True))

    assert decision.full_tp_triggered is False
    assert decision.order_intents == []


def test_block_dca_on_tp_touch_blocks_dca() -> None:
    engine = StrategyEngine()
    state = _position_state()
    candle = _candle(open=100.5, high=106.0, low=98.0, close=99.5)
    settings = Settings(block_dca_on_tp_touch=True, require_close_below_full_tp=True, touch_mode=TouchMode.WICK)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=settings, even_bar_allowed=True))

    assert decision.blocked_by_tp_touch is True
    assert decision.dca_triggered is False


def test_subcover_does_not_work_when_num_sells_lte_5() -> None:
    engine = StrategyEngine()
    state = _position_state(num_sells=5)
    candle = _candle(open=100.0, high=101.0, low=98.0, close=98.0)
    settings = Settings(subcover_confirm_mode=SubcoverConfirmMode.SUBCOVER_TP, touch_mode=TouchMode.WICK)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=settings, even_bar_allowed=True))

    assert decision.subcover_triggered is False


def test_subcover_works_when_num_sells_gt_5() -> None:
    engine = StrategyEngine()
    manager = PositionManager()
    state = _position_state(num_sells=6)
    state = manager.add_short_lot(
        state,
        qty=0.1,
        entry_price=101.0,
        tag="DCA_6",
        created_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        lot_id="lot_2",
        next_level_price=105.0,
    )
    state.num_sells = 6
    candle = _candle(open=100.0, high=101.0, low=99.5, close=99.5)
    settings = Settings(subcover_confirm_mode=SubcoverConfirmMode.SUBCOVER_TP, sub_sell_tp_percent=1.3, touch_mode=TouchMode.WICK)

    decision = engine.evaluate_bar(StrategyContext(candle=candle, state=state, settings=settings, even_bar_allowed=True))

    assert decision.subcover_triggered is True
    assert decision.order_intents[0].intent_type.value == "sub_cover"


def test_even_bar_filter_blocks_signals_on_odd_bar() -> None:
    engine = StrategyEngine()
    decision = engine.evaluate_bar(
        StrategyContext(
            candle=_candle(open=100.0, high=101.0, low=99.0, close=100.0),
            state=_empty_state(),
            settings=Settings(),
            even_bar_allowed=False,
        )
    )

    assert decision.blocked_by_even_bar is True
    assert decision.order_intents == []


def test_allowed_even_bar_can_emit_first_short_signal() -> None:
    engine = StrategyEngine()
    decision = engine.evaluate_bar(
        StrategyContext(
            candle=_candle(open=100.0, high=101.0, low=99.0, close=100.0),
            state=_empty_state(),
            settings=Settings(first_sell_qty_coin=0.09),
            even_bar_allowed=True,
        )
    )

    assert len(decision.order_intents) == 1
    assert decision.order_intents[0].intent_type.value == "first_short"


def test_strategy_engine_returns_order_intent_not_real_order() -> None:
    engine = StrategyEngine()
    decision = engine.evaluate_bar(
        StrategyContext(
            candle=_candle(open=100.0, high=101.0, low=99.0, close=100.0),
            state=_empty_state(),
            settings=Settings(first_sell_qty_coin=0.09),
            even_bar_allowed=True,
        )
    )

    assert isinstance(decision.order_intents[0], OrderIntent)


def test_invalid_state_requires_safe_stop() -> None:
    engine = StrategyEngine()
    invalid_state = BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=1.0,
        avg_price=100.0,
        lots=[],
    )

    decision = engine.evaluate_bar(
        StrategyContext(
            candle=_candle(open=100.0, high=101.0, low=99.0, close=100.0),
            state=invalid_state,
            settings=Settings(),
            even_bar_allowed=True,
        )
    )

    assert decision.safe_stop_required is True
