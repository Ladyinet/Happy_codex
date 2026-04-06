"""Tests for the pure local order lifecycle manager."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.config import BotMode
from bot.execution.order_manager import OrderManager
from bot.storage.models import NormalizedOrder, OrderIntent, OrderIntentType, OrderSide, OrderStatus


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="first_short:1",
        symbol="BTC-USDT",
        side=OrderSide.SELL,
        intent_type=OrderIntentType.FIRST_SHORT,
        qty=0.1,
        price=100.0,
        reason="test",
        created_at=datetime(2026, 4, 9, 12, 1, tzinfo=timezone.utc),
        cycle_id=1,
    )


def _normalized() -> NormalizedOrder:
    return NormalizedOrder(symbol="BTC-USDT", price=100.0, qty=0.1, is_valid=True)


def test_valid_state_transitions() -> None:
    manager = OrderManager()
    order = manager.create_order_record(mode=BotMode.DRY_RUN, intent=_intent(), normalized_order=_normalized())

    sent = manager.mark_sent(order)
    acked = manager.mark_acked(sent.order)

    assert sent.success is True
    assert acked.success is True
    assert acked.order.status == OrderStatus.ACKED


def test_invalid_state_transition_sets_safe_stop_flag() -> None:
    manager = OrderManager()
    order = manager.create_order_record(mode=BotMode.DRY_RUN, intent=_intent(), normalized_order=_normalized())

    invalid = manager.mark_acked(order)

    assert invalid.success is False
    assert invalid.safe_stop_required is True


def test_partial_fill_updates_order() -> None:
    manager = OrderManager()
    order = manager.create_order_record(mode=BotMode.DRY_RUN, intent=_intent(), normalized_order=_normalized())
    order = manager.mark_acked(manager.mark_sent(order).order).order

    partial = manager.mark_partial_fill(order, fill_qty=0.04, fill_price=100.0)

    assert partial.success is True
    assert partial.order.status == OrderStatus.PARTIALLY_FILLED
    assert partial.order.filled_qty == 0.04


def test_filled_after_partial_fill() -> None:
    manager = OrderManager()
    order = manager.create_order_record(mode=BotMode.DRY_RUN, intent=_intent(), normalized_order=_normalized())
    order = manager.mark_acked(manager.mark_sent(order).order).order
    order = manager.mark_partial_fill(order, fill_qty=0.04, fill_price=100.0).order

    filled = manager.mark_filled(order, fill_price=100.0, filled_qty=0.1)

    assert filled.success is True
    assert filled.order.status == OrderStatus.FILLED
    assert filled.order.filled_qty == 0.1


def test_unknown_status_handling() -> None:
    manager = OrderManager()
    order = manager.create_order_record(mode=BotMode.DRY_RUN, intent=_intent(), normalized_order=_normalized())
    order = manager.mark_sent(order).order

    unknown = manager.mark_unknown(order, reason="uncertain local state")

    assert unknown.success is True
    assert unknown.order.status == OrderStatus.UNKNOWN
