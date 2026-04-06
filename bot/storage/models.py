"""Shared enums and dataclasses for storage, execution, and strategy wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from bot.config import BotMode


class OrderSide(StrEnum):
    """Supported order sides."""

    BUY = "buy"
    SELL = "sell"


class OrderIntentType(StrEnum):
    """High-level strategy intent types."""

    FIRST_SHORT = "first_short"
    DCA_SHORT = "dca_short"
    SUB_COVER = "sub_cover"
    FULL_COVER = "full_cover"
    TRAILING_TP = "trailing_tp"


class OrderStatus(StrEnum):
    """Explicit order lifecycle states required by v1."""

    NEW = "NEW"
    SENT = "SENT"
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    """Structured event types for logs and Telegram."""

    BOT_STARTED = "BOT_STARTED"
    FIRST_SHORT = "FIRST_SHORT"
    DCA_SHORT = "DCA_SHORT"
    SUB_COVER = "SUB_COVER"
    FULL_COVER = "FULL_COVER"
    TRAILING_TP = "TRAILING_TP"
    RESET_CYCLE = "RESET_CYCLE"
    SAFE_STOP = "SAFE_STOP"
    ERROR = "ERROR"
    RESTORE_STATE = "RESTORE_STATE"
    DESYNC_DETECTED = "DESYNC_DETECTED"


@dataclass(slots=True)
class InstrumentConstraints:
    """Exchange constraints required for shared order normalization."""

    symbol: str
    tick_size: float
    lot_step: float
    min_qty: float
    min_notional: float
    price_precision: int
    qty_precision: int


@dataclass(slots=True)
class NormalizedOrder:
    """Normalized order result shared by dry_run and future live mode."""

    symbol: str
    price: float | None
    qty: float
    is_valid: bool
    reason: str | None = None


@dataclass(slots=True)
class Lot:
    """One open lot in the local LIFO lot-book."""

    id: str
    qty: float
    entry_price: float
    tag: str
    usdt_value: float
    created_at: datetime
    open_sequence: int | None = None
    source_order_id: str | None = None


@dataclass(slots=True)
class BotState:
    """Persisted and runtime bot state for one symbol and timeframe."""

    mode: BotMode
    symbol: str
    timeframe: str
    cycle_id: int = 0
    pos_size_abs: float = 0.0
    pos_proceeds_usdt: float = 0.0
    avg_price: float = 0.0
    num_sells: int = 0
    last_fill_price: float | None = None
    next_level_price: float | None = None
    lots: list[Lot] = field(default_factory=list)
    trailing_active: bool = False
    trailing_min: float | None = None
    cycle_base_qty: float = 0.0
    reset_cycle: bool = False
    orders_last_3min: list[datetime] = field(default_factory=list)
    fills_this_bar: int = 0
    subcovers_this_bar: int = 0
    last_candle_time: datetime | None = None
    last_sync_time: datetime | None = None
    desync_detected: bool = False
    safe_stop_active: bool = False
    safe_stop_reason: str | None = None


@dataclass(slots=True)
class OrderIntent:
    """Strategy output before normalization and execution."""

    intent_id: str
    symbol: str
    side: OrderSide
    intent_type: OrderIntentType
    qty: float
    price: float | None
    reason: str
    created_at: datetime
    cycle_id: int
    client_order_id: str | None = None


@dataclass(slots=True)
class OrderRecord:
    """Persistent order record with lifecycle tracking."""

    mode: BotMode
    order_id: str
    client_order_id: str | None
    symbol: str
    side: OrderSide
    intent_type: OrderIntentType
    status: OrderStatus
    requested_qty: float
    requested_price: float | None
    normalized_qty: float | None
    normalized_price: float | None
    filled_qty: float = 0.0
    avg_fill_price: float | None = None
    cycle_id: int = 0
    reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    exchange_order_id: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class FillRecord:
    """Persistent fill record for partial and complete executions."""

    fill_id: str | None
    order_id: str
    client_order_id: str | None
    symbol: str
    side: OrderSide
    price: float
    qty: float
    fee: float | None
    occurred_at: datetime
    raw_status: str | None = None


@dataclass(slots=True)
class EventRecord:
    """Structured event for audit logs, storage, and Telegram."""

    event_id: str
    event_type: EventType
    mode: BotMode
    symbol: str
    timeframe: str
    reason: str | None
    created_at: datetime
    price: float | None = None
    qty: float | None = None
    position_size: float | None = None
    avg_price: float | None = None
    pnl: float | None = None
    cycle_id: int | None = None
    payload_json: str | None = None


@dataclass(slots=True)
class SubscriberRecord:
    """Telegram subscriber stored in local SQLite state."""

    chat_id: int
    username: str | None
    first_name: str | None
    created_at: datetime
    is_active: bool = True


@dataclass(slots=True)
class LotHistoryRecord:
    """Persistent record of lot open and close history."""

    history_id: str
    lot_id: str
    mode: BotMode
    symbol: str
    timeframe: str
    cycle_id: int
    action: str
    qty: float
    price: float
    related_order_id: str | None
    occurred_at: datetime


@dataclass(slots=True)
class SafeStopRecord:
    """Persistent record for safe-stop activation and optional resolution."""

    safe_stop_id: str
    mode: BotMode
    symbol: str
    timeframe: str
    reason: str
    created_at: datetime
    details_json: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    """Outcome of one executor step."""

    order: OrderRecord | None = None
    fills: list[FillRecord] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
