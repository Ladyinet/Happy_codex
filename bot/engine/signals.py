"""Shared market and strategy signal models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.config import Settings
from bot.storage.models import BotState, EventRecord, InstrumentConstraints, OrderIntent


@dataclass(slots=True)
class Candle:
    """Normalized closed-candle representation."""

    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


@dataclass(slots=True)
class StrategyContext:
    """All inputs required for a single-bar strategy evaluation."""

    candle: Candle
    state: BotState
    settings: Settings
    even_bar_allowed: bool
    constraints: InstrumentConstraints | None = None


@dataclass(slots=True)
class StrategyDecision:
    """Output of one strategy evaluation step."""

    order_intents: list[OrderIntent] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    updated_state: BotState | None = None
    full_tp_triggered: bool = False
    trailing_exit_triggered: bool = False
    subcover_triggered: bool = False
    dca_triggered: bool = False
    blocked_by_even_bar: bool = False
    blocked_by_tp_touch: bool = False
    safe_stop_required: bool = False
    safe_stop_reason: str | None = None
