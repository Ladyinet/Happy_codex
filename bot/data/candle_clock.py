"""Even-bar clock utilities for UTC-aligned candle processing."""

from __future__ import annotations

import math
from datetime import datetime

from bot.config import EvenBarAnchorMode
from bot.utils.time_utils import datetime_from_iso, ensure_utc, timeframe_to_seconds, utc_day_start


def calculate_bars_from_anchor(
    *,
    bar_time_utc: datetime,
    anchor_time_utc: datetime,
    timeframe_seconds: int,
) -> int:
    """Return the zero-based bar index from the given anchor.

    Formula:
    bars_from_anchor = floor((bar_time_utc - anchor_time_utc) / timeframe_seconds)
    """

    bar_time = ensure_utc(bar_time_utc)
    anchor_time = ensure_utc(anchor_time_utc)
    delta_seconds = (bar_time - anchor_time).total_seconds()
    return math.floor(delta_seconds / timeframe_seconds)


class CandleClock:
    """Tracks closed bars and evaluates the even-bar filter deterministically."""

    def __init__(
        self,
        timeframe: str,
        anchor_mode: EvenBarAnchorMode = EvenBarAnchorMode.UTC_DAY_START,
        *,
        live_start_time: datetime | None = None,
        fixed_timestamp: datetime | str | None = None,
    ) -> None:
        self.timeframe = timeframe
        self.timeframe_seconds = timeframe_to_seconds(timeframe)
        self.anchor_mode = anchor_mode
        self.live_start_time = ensure_utc(live_start_time) if live_start_time is not None else None
        self.fixed_timestamp = self._parse_optional_anchor(fixed_timestamp)
        self._validate_configuration()

    def is_new_bar(self, previous_close_time: datetime | None, current_close_time: datetime) -> bool:
        """Return whether the current closed candle advances processing to a new bar."""

        current_utc = ensure_utc(current_close_time)
        if previous_close_time is None:
            return True
        previous_utc = ensure_utc(previous_close_time)
        return current_utc > previous_utc

    def anchor_time(self, close_time: datetime) -> datetime:
        """Resolve the effective anchor time for a given bar."""

        bar_time = ensure_utc(close_time)
        if self.anchor_mode == EvenBarAnchorMode.UTC_DAY_START:
            return utc_day_start(bar_time)
        if self.anchor_mode == EvenBarAnchorMode.LIVE_START:
            if self.live_start_time is None:
                raise ValueError("live_start_time is required for EVEN_BAR_ANCHOR_MODE=live_start.")
            return self.live_start_time
        if self.fixed_timestamp is None:
            raise ValueError("fixed_timestamp is required for EVEN_BAR_ANCHOR_MODE=fixed_timestamp.")
        return self.fixed_timestamp

    def bars_from_anchor(self, close_time: datetime) -> int:
        """Return the bar index from the configured anchor."""

        bar_time = ensure_utc(close_time)
        anchor_time = self.anchor_time(bar_time)
        return calculate_bars_from_anchor(
            bar_time_utc=bar_time,
            anchor_time_utc=anchor_time,
            timeframe_seconds=self.timeframe_seconds,
        )

    def is_bar_allowed(self, close_time: datetime) -> bool:
        """Return whether the bar passes the even-bar filter."""

        return self.bars_from_anchor(close_time) % 2 == 0

    def _validate_configuration(self) -> None:
        if self.anchor_mode == EvenBarAnchorMode.LIVE_START and self.live_start_time is None:
            raise ValueError("live_start_time is required for EVEN_BAR_ANCHOR_MODE=live_start.")
        if self.anchor_mode == EvenBarAnchorMode.FIXED_TIMESTAMP and self.fixed_timestamp is None:
            raise ValueError("fixed_timestamp is required for EVEN_BAR_ANCHOR_MODE=fixed_timestamp.")

    @staticmethod
    def _parse_optional_anchor(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        return datetime_from_iso(value)
