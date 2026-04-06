"""Tests for the SQLite repository layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from bot.config import BotMode
from bot.storage.models import BotState, Lot, SafeStopRecord, SubscriberRecord
from bot.storage.schema import REQUIRED_TABLES
from bot.storage.storage import SQLiteStorage


@pytest.mark.asyncio
async def test_init_db_creates_required_tables(tmp_path) -> None:
    """Schema initialization should create all required tables."""

    db_path = tmp_path / "state.db"
    storage = SQLiteStorage(str(db_path))

    await storage.init_db()

    async with aiosqlite.connect(db_path) as connection:
        cursor = await connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        rows = await cursor.fetchall()

    table_names = {row[0] for row in rows}
    for table_name in REQUIRED_TABLES:
        assert table_name in table_names


@pytest.mark.asyncio
async def test_save_and_load_bot_state_round_trip(tmp_path) -> None:
    """BotState should round-trip through SQLite with lots and counters intact."""

    db_path = tmp_path / "state.db"
    storage = SQLiteStorage(str(db_path))
    await storage.init_db()

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    state = BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        cycle_id=7,
        pos_size_abs=0.27,
        pos_proceeds_usdt=18000.5,
        avg_price=66668.5,
        num_sells=3,
        last_fill_price=66700.0,
        next_level_price=66900.0,
        lots=[
            Lot(
                id="lot_1",
                qty=0.09,
                entry_price=66500.0,
                tag="FIRST_SHORT",
                usdt_value=5985.0,
                created_at=now,
                open_sequence=0,
                source_order_id="order_1",
            ),
        ],
        trailing_active=True,
        trailing_min=66100.0,
        cycle_base_qty=0.09,
        reset_cycle=False,
        orders_last_3min=[now - timedelta(minutes=2), now - timedelta(minutes=1)],
        fills_this_bar=2,
        subcovers_this_bar=1,
        last_candle_time=now,
        last_sync_time=now,
        desync_detected=False,
        safe_stop_active=False,
        safe_stop_reason=None,
    )

    await storage.save_bot_state(state)
    loaded = await storage.load_bot_state(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")

    assert loaded is not None
    assert loaded.mode == state.mode
    assert loaded.symbol == state.symbol
    assert loaded.timeframe == state.timeframe
    assert loaded.cycle_id == state.cycle_id
    assert loaded.avg_price == state.avg_price
    assert loaded.trailing_active is True
    assert loaded.fills_this_bar == 2
    assert loaded.subcovers_this_bar == 1
    assert len(loaded.orders_last_3min) == 2
    assert len(loaded.lots) == 1
    assert loaded.lots[0].id == "lot_1"
    assert loaded.lots[0].open_sequence == 0


@pytest.mark.asyncio
async def test_add_list_and_deactivate_subscriber(tmp_path) -> None:
    """Subscribers should be added, listed, and deactivated locally."""

    db_path = tmp_path / "state.db"
    storage = SQLiteStorage(str(db_path))
    await storage.init_db()

    created_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
    subscriber = SubscriberRecord(
        chat_id=123456,
        username="alice",
        first_name="Alice",
        created_at=created_at,
    )

    await storage.add_subscriber(subscriber)
    active = await storage.list_active_subscribers()
    assert len(active) == 1
    assert active[0].chat_id == 123456

    await storage.deactivate_subscriber(123456)
    active_after = await storage.list_active_subscribers()
    assert active_after == []


@pytest.mark.asyncio
async def test_save_safe_stop_reason_persists_log_and_updates_state(tmp_path) -> None:
    """Safe-stop reason should be logged and reflected in the current bot_state snapshot."""

    db_path = tmp_path / "state.db"
    storage = SQLiteStorage(str(db_path))
    await storage.init_db()

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    state = BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")
    await storage.save_bot_state(state)

    record = SafeStopRecord(
        safe_stop_id="ss_1",
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        reason="desync detected",
        details_json='{"source":"test"}',
        created_at=now,
    )
    await storage.save_safe_stop_reason(record)

    loaded = await storage.load_bot_state(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")
    assert loaded is not None
    assert loaded.safe_stop_active is True
    assert loaded.safe_stop_reason == "desync detected"

    async with aiosqlite.connect(db_path) as connection:
        cursor = await connection.execute(
            "SELECT reason, details_json FROM safe_stop_log WHERE safe_stop_id = ?",
            ("ss_1",),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == "desync detected"
    assert row[1] == '{"source":"test"}'
