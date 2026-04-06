"""Time-alignment helpers for closed-candle processing."""

from __future__ import annotations

from datetime import datetime

from bot.config import EvenBarAnchorMode


class CandleClock:
    """Tracks candle boundaries and even-bar anchoring."""

    def __init__(self, timeframe: str, anchor_mode: EvenBarAnchorMode) -> None:
        self.timeframe = timeframe
        self.anchor_mode = anchor_mode

    def is_new_bar(self, previous_close_time: datetime | None, current_close_time: datetime) -> bool:
        """Return whether the current candle starts a new processing step."""
        raise NotImplementedError

    def bars_from_anchor(self, close_time: datetime) -> int:
        """Return the zero-based bar index from the configured anchor."""
        raise NotImplementedError
