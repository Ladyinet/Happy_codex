"""SQLite repository implementation for the local v1 storage layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Iterable

import aiosqlite

from bot.config import BotMode
from bot.storage.models import (
    BotState,
    EventRecord,
    FillRecord,
    Lot,
    LotHistoryRecord,
    OrderRecord,
    OrderStatus,
    SafeStopRecord,
    SubscriberRecord,
)
from bot.storage.schema import SCHEMA_STATEMENTS


class SQLiteStorage:
    """Concrete SQLite repository for local bot state."""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path))

    async def init_db(self) -> None:
        """Initialize the SQLite schema."""

        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode=WAL;")
            await connection.execute("PRAGMA foreign_keys=ON;")
            for statement in SCHEMA_STATEMENTS:
                await connection.execute(statement)
            await connection.commit()

    async def initialize(self) -> None:
        """Backward-compatible alias for schema initialization."""

        await self.init_db()

    async def close(self) -> None:
        """Close repository resources.

        The repository currently uses per-call connections, so there is no shared handle to close.
        """

    async def save_bot_state(self, state: BotState) -> None:
        """Persist the full bot state snapshot transactionally."""

        state_record = _serialize_bot_state(state)
        async with self._connect() as connection:
            await connection.execute("BEGIN")
            try:
                await connection.execute(
                    """
                    INSERT INTO bot_state (
                        mode, symbol, timeframe, cycle_id, pos_size_abs, pos_proceeds_usdt, avg_price,
                        num_sells, last_fill_price, next_level_price, trailing_active, trailing_min,
                        cycle_base_qty, reset_cycle, last_candle_time, last_sync_time, desync_detected,
                        safe_stop_active, safe_stop_reason, updated_at
                    ) VALUES (
                        :mode, :symbol, :timeframe, :cycle_id, :pos_size_abs, :pos_proceeds_usdt, :avg_price,
                        :num_sells, :last_fill_price, :next_level_price, :trailing_active, :trailing_min,
                        :cycle_base_qty, :reset_cycle, :last_candle_time, :last_sync_time, :desync_detected,
                        :safe_stop_active, :safe_stop_reason, :updated_at
                    )
                    ON CONFLICT(mode, symbol, timeframe) DO UPDATE SET
                        cycle_id = excluded.cycle_id,
                        pos_size_abs = excluded.pos_size_abs,
                        pos_proceeds_usdt = excluded.pos_proceeds_usdt,
                        avg_price = excluded.avg_price,
                        num_sells = excluded.num_sells,
                        last_fill_price = excluded.last_fill_price,
                        next_level_price = excluded.next_level_price,
                        trailing_active = excluded.trailing_active,
                        trailing_min = excluded.trailing_min,
                        cycle_base_qty = excluded.cycle_base_qty,
                        reset_cycle = excluded.reset_cycle,
                        last_candle_time = excluded.last_candle_time,
                        last_sync_time = excluded.last_sync_time,
                        desync_detected = excluded.desync_detected,
                        safe_stop_active = excluded.safe_stop_active,
                        safe_stop_reason = excluded.safe_stop_reason,
                        updated_at = excluded.updated_at
                    """,
                    state_record,
                )

                await connection.execute(
                    """
                    DELETE FROM lots
                    WHERE mode = ? AND symbol = ? AND timeframe = ?
                    """,
                    (state.mode.value, state.symbol, state.timeframe),
                )
                for index, lot in enumerate(state.lots):
                    await connection.execute(
                        """
                        INSERT INTO lots (
                            lot_id, mode, symbol, timeframe, cycle_id, open_sequence, qty,
                            entry_price, tag, usdt_value, created_at, source_order_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _serialize_lot(
                            mode=state.mode,
                            symbol=state.symbol,
                            timeframe=state.timeframe,
                            cycle_id=state.cycle_id,
                            lot=lot,
                            fallback_sequence=index,
                        ),
                    )

                await connection.execute(
                    """
                    DELETE FROM rolling_window_entries
                    WHERE mode = ? AND symbol = ? AND timeframe = ?
                    """,
                    (state.mode.value, state.symbol, state.timeframe),
                )
                for entry_index, created_at in enumerate(state.orders_last_3min):
                    await connection.execute(
                        """
                        INSERT INTO rolling_window_entries (
                            entry_id, mode, symbol, timeframe, event_type, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{state.mode.value}:{state.symbol}:{state.timeframe}:{entry_index}:{_serialize_datetime(created_at)}",
                            state.mode.value,
                            state.symbol,
                            state.timeframe,
                            "order",
                            _serialize_datetime(created_at),
                        ),
                    )

                await connection.execute(
                    """
                    DELETE FROM bar_counters
                    WHERE mode = ? AND symbol = ? AND timeframe = ?
                    """,
                    (state.mode.value, state.symbol, state.timeframe),
                )
                if state.last_candle_time is not None:
                    await connection.execute(
                        """
                        INSERT INTO bar_counters (
                            mode, symbol, timeframe, bar_time, fills_this_bar, subcovers_this_bar, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            state.mode.value,
                            state.symbol,
                            state.timeframe,
                            _serialize_datetime(state.last_candle_time),
                            state.fills_this_bar,
                            state.subcovers_this_bar,
                            state_record["updated_at"],
                        ),
                    )

                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def load_bot_state(self, mode: BotMode, symbol: str, timeframe: str) -> BotState | None:
        """Load one full bot state snapshot, including lots and counters."""

        async with self._connect() as connection:
            state_cursor = await connection.execute(
                """
                SELECT *
                FROM bot_state
                WHERE mode = ? AND symbol = ? AND timeframe = ?
                """,
                (mode.value, symbol, timeframe),
            )
            state_row = await state_cursor.fetchone()
            if state_row is None:
                return None

            lots = await self.list_open_lots(mode=mode, symbol=symbol, timeframe=timeframe)
            rolling_cursor = await connection.execute(
                """
                SELECT created_at
                FROM rolling_window_entries
                WHERE mode = ? AND symbol = ? AND timeframe = ?
                ORDER BY created_at ASC
                """,
                (mode.value, symbol, timeframe),
            )
            rolling_rows = await rolling_cursor.fetchall()
            orders_last_3min = [_deserialize_datetime(row["created_at"]) for row in rolling_rows]

            counter_cursor = await connection.execute(
                """
                SELECT fills_this_bar, subcovers_this_bar
                FROM bar_counters
                WHERE mode = ? AND symbol = ? AND timeframe = ?
                ORDER BY bar_time DESC
                LIMIT 1
                """,
                (mode.value, symbol, timeframe),
            )
            counter_row = await counter_cursor.fetchone()
            fills_this_bar = int(counter_row["fills_this_bar"]) if counter_row is not None else 0
            subcovers_this_bar = int(counter_row["subcovers_this_bar"]) if counter_row is not None else 0

        return _deserialize_bot_state(
            state_row=state_row,
            lots=lots,
            orders_last_3min=orders_last_3min,
            fills_this_bar=fills_this_bar,
            subcovers_this_bar=subcovers_this_bar,
        )

    async def save_lot(
        self,
        mode: BotMode,
        symbol: str,
        timeframe: str,
        cycle_id: int,
        lot: Lot,
    ) -> None:
        """Persist or replace one open lot."""

        async with self._connect() as connection:
            sequence = lot.open_sequence
            if sequence is None:
                cursor = await connection.execute(
                    """
                    SELECT COALESCE(MAX(open_sequence), -1) + 1 AS next_sequence
                    FROM lots
                    WHERE mode = ? AND symbol = ? AND timeframe = ?
                    """,
                    (mode.value, symbol, timeframe),
                )
                row = await cursor.fetchone()
                sequence = int(row["next_sequence"])

            await connection.execute(
                """
                INSERT OR REPLACE INTO lots (
                    lot_id, mode, symbol, timeframe, cycle_id, open_sequence, qty,
                    entry_price, tag, usdt_value, created_at, source_order_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _serialize_lot(
                    mode=mode,
                    symbol=symbol,
                    timeframe=timeframe,
                    cycle_id=cycle_id,
                    lot=lot,
                    fallback_sequence=sequence,
                ),
            )
            await connection.commit()

    async def list_open_lots(self, mode: BotMode, symbol: str, timeframe: str) -> list[Lot]:
        """Return all open lots in creation order."""

        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT lot_id, qty, entry_price, tag, usdt_value, created_at, open_sequence, source_order_id
                FROM lots
                WHERE mode = ? AND symbol = ? AND timeframe = ?
                ORDER BY open_sequence ASC
                """,
                (mode.value, symbol, timeframe),
            )
            rows = await cursor.fetchall()
        return [_deserialize_lot(row) for row in rows]

    async def append_lot_history(self, entries: Iterable[LotHistoryRecord]) -> None:
        """Append lot history entries."""

        serialized = [
            (
                entry.history_id,
                entry.lot_id,
                entry.mode.value,
                entry.symbol,
                entry.timeframe,
                entry.cycle_id,
                entry.action,
                entry.qty,
                entry.price,
                entry.related_order_id,
                _serialize_datetime(entry.occurred_at),
            )
            for entry in entries
        ]
        if not serialized:
            return

        async with self._connect() as connection:
            await connection.executemany(
                """
                INSERT INTO lot_history (
                    history_id, lot_id, mode, symbol, timeframe, cycle_id, action,
                    qty, price, related_order_id, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                serialized,
            )
            await connection.commit()

    async def save_order(self, order: OrderRecord) -> None:
        """Insert or replace a full order record."""

        created_at = _serialize_datetime(order.created_at or _utc_now())
        updated_at = _serialize_datetime(order.updated_at or order.created_at or _utc_now())
        async with self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO orders (
                    order_id, client_order_id, mode, symbol, side, intent_type, status,
                    requested_qty, requested_price, normalized_qty, normalized_price,
                    filled_qty, avg_fill_price, cycle_id, reason, exchange_order_id,
                    last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    client_order_id = excluded.client_order_id,
                    mode = excluded.mode,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    intent_type = excluded.intent_type,
                    status = excluded.status,
                    requested_qty = excluded.requested_qty,
                    requested_price = excluded.requested_price,
                    normalized_qty = excluded.normalized_qty,
                    normalized_price = excluded.normalized_price,
                    filled_qty = excluded.filled_qty,
                    avg_fill_price = excluded.avg_fill_price,
                    cycle_id = excluded.cycle_id,
                    reason = excluded.reason,
                    exchange_order_id = excluded.exchange_order_id,
                    last_error = excluded.last_error,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    order.order_id,
                    order.client_order_id,
                    order.mode.value,
                    order.symbol,
                    order.side.value,
                    order.intent_type.value,
                    order.status.value,
                    order.requested_qty,
                    order.requested_price,
                    order.normalized_qty,
                    order.normalized_price,
                    order.filled_qty,
                    order.avg_fill_price,
                    order.cycle_id,
                    order.reason,
                    order.exchange_order_id,
                    order.last_error,
                    created_at,
                    updated_at,
                ),
            )
            await connection.commit()

    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        *,
        filled_qty: float | None = None,
        avg_fill_price: float | None = None,
        exchange_order_id: str | None = None,
        last_error: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Update the mutable status fields of an order."""

        update_timestamp = _serialize_datetime(updated_at or _utc_now())
        async with self._connect() as connection:
            await connection.execute(
                """
                UPDATE orders
                SET status = ?,
                    filled_qty = COALESCE(?, filled_qty),
                    avg_fill_price = COALESCE(?, avg_fill_price),
                    exchange_order_id = COALESCE(?, exchange_order_id),
                    last_error = ?,
                    updated_at = ?
                WHERE order_id = ?
                """,
                (
                    status.value,
                    filled_qty,
                    avg_fill_price,
                    exchange_order_id,
                    last_error,
                    update_timestamp,
                    order_id,
                ),
            )
            await connection.commit()

    async def save_fill(self, fill: FillRecord) -> None:
        """Persist one fill record immediately."""

        async with self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO fills (
                    fill_id, order_id, client_order_id, symbol, side, price, qty, fee, raw_status, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.fill_id,
                    fill.order_id,
                    fill.client_order_id,
                    fill.symbol,
                    fill.side.value,
                    fill.price,
                    fill.qty,
                    fill.fee,
                    fill.raw_status,
                    _serialize_datetime(fill.occurred_at),
                ),
            )
            await connection.commit()

    async def save_event(self, event: EventRecord) -> None:
        """Persist one structured event."""

        async with self._connect() as connection:
            await connection.execute(
                """
                INSERT OR REPLACE INTO events (
                    event_id, mode, symbol, timeframe, event_type, reason,
                    price, qty, position_size, avg_price, pnl, cycle_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.mode.value,
                    event.symbol,
                    event.timeframe,
                    event.event_type.value,
                    event.reason,
                    event.price,
                    event.qty,
                    event.position_size,
                    event.avg_price,
                    event.pnl,
                    event.cycle_id,
                    event.payload_json,
                    _serialize_datetime(event.created_at),
                ),
            )
            await connection.commit()

    async def add_subscriber(self, subscriber: SubscriberRecord) -> None:
        """Create or reactivate a Telegram subscriber."""

        async with self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO subscribers (chat_id, username, first_name, created_at, is_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    is_active = 1
                """,
                (
                    subscriber.chat_id,
                    subscriber.username,
                    subscriber.first_name,
                    _serialize_datetime(subscriber.created_at),
                    1 if subscriber.is_active else 0,
                ),
            )
            await connection.commit()

    async def deactivate_subscriber(self, chat_id: int) -> None:
        """Deactivate a Telegram subscriber."""

        async with self._connect() as connection:
            await connection.execute(
                """
                UPDATE subscribers
                SET is_active = 0
                WHERE chat_id = ?
                """,
                (chat_id,),
            )
            await connection.commit()

    async def list_active_subscribers(self) -> list[SubscriberRecord]:
        """Return all active Telegram subscribers."""

        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT chat_id, username, first_name, created_at, is_active
                FROM subscribers
                WHERE is_active = 1
                ORDER BY created_at ASC, chat_id ASC
                """,
            )
            rows = await cursor.fetchall()
        return [
            SubscriberRecord(
                chat_id=int(row["chat_id"]),
                username=row["username"],
                first_name=row["first_name"],
                created_at=_deserialize_datetime(row["created_at"]),
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    async def save_safe_stop_reason(self, record: SafeStopRecord) -> None:
        """Persist a safe-stop record and mark the current state as blocked when present."""

        async with self._connect() as connection:
            await connection.execute("BEGIN")
            try:
                await connection.execute(
                    """
                    INSERT OR REPLACE INTO safe_stop_log (
                        safe_stop_id, mode, symbol, timeframe, reason,
                        details_json, created_at, resolved_at, resolved_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.safe_stop_id,
                        record.mode.value,
                        record.symbol,
                        record.timeframe,
                        record.reason,
                        record.details_json,
                        _serialize_datetime(record.created_at),
                        _serialize_datetime(record.resolved_at),
                        record.resolved_by,
                    ),
                )
                await connection.execute(
                    """
                    UPDATE bot_state
                    SET safe_stop_active = 1,
                        safe_stop_reason = ?,
                        updated_at = ?
                    WHERE mode = ? AND symbol = ? AND timeframe = ?
                    """,
                    (
                        record.reason,
                        _serialize_datetime(record.created_at),
                        record.mode.value,
                        record.symbol,
                        record.timeframe,
                    ),
                )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def load_state(self, mode: BotMode, symbol: str, timeframe: str) -> BotState | None:
        """Backward-compatible alias for load_bot_state()."""

        return await self.load_bot_state(mode=mode, symbol=symbol, timeframe=timeframe)

    async def save_state(self, state: BotState) -> None:
        """Backward-compatible alias for save_bot_state()."""

        await self.save_bot_state(state)

    async def load_open_lots(self, mode: BotMode, symbol: str, timeframe: str) -> list[Lot]:
        """Backward-compatible alias for list_open_lots()."""

        return await self.list_open_lots(mode=mode, symbol=symbol, timeframe=timeframe)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.db_path)
        connection.row_factory = aiosqlite.Row
        try:
            yield connection
        finally:
            await connection.close()


def _serialize_bot_state(state: BotState) -> dict[str, str | float | int | None]:
    """Serialize the scalar part of BotState for storage."""

    return {
        "mode": state.mode.value,
        "symbol": state.symbol,
        "timeframe": state.timeframe,
        "cycle_id": state.cycle_id,
        "pos_size_abs": state.pos_size_abs,
        "pos_proceeds_usdt": state.pos_proceeds_usdt,
        "avg_price": state.avg_price,
        "num_sells": state.num_sells,
        "last_fill_price": state.last_fill_price,
        "next_level_price": state.next_level_price,
        "trailing_active": int(state.trailing_active),
        "trailing_min": state.trailing_min,
        "cycle_base_qty": state.cycle_base_qty,
        "reset_cycle": int(state.reset_cycle),
        "last_candle_time": _serialize_datetime(state.last_candle_time),
        "last_sync_time": _serialize_datetime(state.last_sync_time),
        "desync_detected": int(state.desync_detected),
        "safe_stop_active": int(state.safe_stop_active),
        "safe_stop_reason": state.safe_stop_reason,
        "updated_at": _serialize_datetime(_utc_now()),
    }


def _deserialize_bot_state(
    *,
    state_row: aiosqlite.Row,
    lots: list[Lot],
    orders_last_3min: list[datetime],
    fills_this_bar: int,
    subcovers_this_bar: int,
) -> BotState:
    """Deserialize one full BotState snapshot from storage rows."""

    return BotState(
        mode=BotMode(state_row["mode"]),
        symbol=str(state_row["symbol"]),
        timeframe=str(state_row["timeframe"]),
        cycle_id=int(state_row["cycle_id"]),
        pos_size_abs=float(state_row["pos_size_abs"]),
        pos_proceeds_usdt=float(state_row["pos_proceeds_usdt"]),
        avg_price=float(state_row["avg_price"]),
        num_sells=int(state_row["num_sells"]),
        last_fill_price=_to_optional_float(state_row["last_fill_price"]),
        next_level_price=_to_optional_float(state_row["next_level_price"]),
        lots=lots,
        trailing_active=bool(state_row["trailing_active"]),
        trailing_min=_to_optional_float(state_row["trailing_min"]),
        cycle_base_qty=float(state_row["cycle_base_qty"]),
        reset_cycle=bool(state_row["reset_cycle"]),
        orders_last_3min=orders_last_3min,
        fills_this_bar=fills_this_bar,
        subcovers_this_bar=subcovers_this_bar,
        last_candle_time=_deserialize_datetime(state_row["last_candle_time"]),
        last_sync_time=_deserialize_datetime(state_row["last_sync_time"]),
        desync_detected=bool(state_row["desync_detected"]),
        safe_stop_active=bool(state_row["safe_stop_active"]),
        safe_stop_reason=state_row["safe_stop_reason"],
    )


def _serialize_lot(
    *,
    mode: BotMode,
    symbol: str,
    timeframe: str,
    cycle_id: int,
    lot: Lot,
    fallback_sequence: int,
) -> tuple[object, ...]:
    """Serialize one Lot for the SQLite lots table."""

    return (
        lot.id,
        mode.value,
        symbol,
        timeframe,
        cycle_id,
        lot.open_sequence if lot.open_sequence is not None else fallback_sequence,
        lot.qty,
        lot.entry_price,
        lot.tag,
        lot.usdt_value,
        _serialize_datetime(lot.created_at),
        lot.source_order_id,
    )


def _deserialize_lot(row: aiosqlite.Row) -> Lot:
    """Deserialize one Lot row from SQLite."""

    return Lot(
        id=str(row["lot_id"]),
        qty=float(row["qty"]),
        entry_price=float(row["entry_price"]),
        tag=str(row["tag"]),
        usdt_value=float(row["usdt_value"]),
        created_at=_deserialize_datetime(row["created_at"]),
        open_sequence=int(row["open_sequence"]),
        source_order_id=row["source_order_id"],
    )


def _serialize_datetime(value: datetime | None) -> str | None:
    """Store datetimes consistently in UTC ISO 8601 format."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _deserialize_datetime(value: str | None) -> datetime | None:
    """Load datetimes from the shared UTC ISO 8601 storage format."""

    if value is None:
        return None
    return datetime.fromisoformat(value)


def _to_optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)
