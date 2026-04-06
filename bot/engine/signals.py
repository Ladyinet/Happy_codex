"""Shared market and strategy signal models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot.config import TouchMode
from bot.storage.models import BotState, EventRecord, OrderIntent


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
    touch_mode: TouchMode
    even_bar_allowed: bool


@dataclass(slots=True)
class StrategyDecision:
    """Output of one strategy evaluation step."""

    order_intents: list[OrderIntent] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    safe_stop_reason: str | None = None
