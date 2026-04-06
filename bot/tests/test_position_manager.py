"""Tests for the local position manager."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.config import BotMode
from bot.engine.position_manager import PositionManager
from bot.storage.models import BotState


def _state() -> BotState:
    return BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")


def _ts(minute: int) -> datetime:
    return datetime(2026, 4, 8, 12, minute, tzinfo=timezone.utc)


def test_adding_lot_updates_position_and_open_sequence() -> None:
    manager = PositionManager()
    state = manager.add_short_lot(
        _state(),
        qty=0.1,
        entry_price=100.0,
        tag="FIRST_SHORT",
        created_at=_ts(0),
        lot_id="lot_1",
    )

    assert len(state.lots) == 1
    assert state.lots[0].open_sequence == 0
    assert state.pos_size_abs == 0.1
    assert state.avg_price == 100.0
    assert state.last_fill_price == 100.0


def test_lifo_returns_last_lot() -> None:
    manager = PositionManager()
    state = manager.add_short_lot(_state(), qty=0.1, entry_price=100.0, tag="A", created_at=_ts(0), lot_id="lot_1")
    state = manager.add_short_lot(state, qty=0.2, entry_price=110.0, tag="B", created_at=_ts(1), lot_id="lot_2")

    last_lot = manager.get_last_lot(state)

    assert last_lot is not None
    assert last_lot.id == "lot_2"
    assert [lot.id for lot in state.lots] == ["lot_1", "lot_2"]


def test_partial_close_last_lot_keeps_lifo_order() -> None:
    manager = PositionManager()
    state = manager.add_short_lot(_state(), qty=0.1, entry_price=100.0, tag="A", created_at=_ts(0), lot_id="lot_1")
    state = manager.add_short_lot(state, qty=0.2, entry_price=110.0, tag="B", created_at=_ts(1), lot_id="lot_2")

    updated = manager.close_last_lot(state, close_qty=0.05, close_price=105.0)

    assert len(updated.lots) == 2
    assert updated.lots[-1].id == "lot_2"
    assert updated.lots[-1].qty == 0.15
    assert updated.pos_size_abs == 0.25


def test_full_close_last_lot_removes_it() -> None:
    manager = PositionManager()
    state = manager.add_short_lot(_state(), qty=0.1, entry_price=100.0, tag="A", created_at=_ts(0), lot_id="lot_1")
    state = manager.add_short_lot(state, qty=0.2, entry_price=110.0, tag="B", created_at=_ts(1), lot_id="lot_2")

    updated = manager.close_last_lot(state, close_qty=0.2, close_price=104.0)

    assert len(updated.lots) == 1
    assert updated.lots[0].id == "lot_1"
    assert updated.pos_size_abs == 0.1


def test_avg_price_and_position_recalculate_correctly() -> None:
    manager = PositionManager()
    state = manager.add_short_lot(_state(), qty=0.1, entry_price=100.0, tag="A", created_at=_ts(0), lot_id="lot_1")
    state = manager.add_short_lot(state, qty=0.2, entry_price=110.0, tag="B", created_at=_ts(1), lot_id="lot_2")

    assert round(state.pos_size_abs, 8) == 0.3
    assert round(state.avg_price, 8) == round((0.1 * 100.0 + 0.2 * 110.0) / 0.3, 8)


def test_multiple_lots_preserve_order() -> None:
    manager = PositionManager()
    state = _state()
    state = manager.add_short_lot(state, qty=0.1, entry_price=100.0, tag="A", created_at=_ts(0), lot_id="lot_1")
    state = manager.add_short_lot(state, qty=0.1, entry_price=101.0, tag="B", created_at=_ts(1), lot_id="lot_2")
    state = manager.add_short_lot(state, qty=0.1, entry_price=102.0, tag="C", created_at=_ts(2), lot_id="lot_3")

    assert [lot.id for lot in state.lots] == ["lot_1", "lot_2", "lot_3"]
    assert [lot.open_sequence for lot in state.lots] == [0, 1, 2]
