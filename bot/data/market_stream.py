"""Internal candle-update buffering utilities for market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from bot.utils.time_utils import ensure_utc


@dataclass(slots=True)
class Candle:
    """Normalized UTC-aware candle update.

    The same model is used for in-progress bar updates and for closed-bar emission.
    """

    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = False

    def normalized(self) -> "Candle":
        """Return a copy of the candle with UTC-normalized datetimes."""

        return Candle(
            open_time=ensure_utc(self.open_time),
            close_time=ensure_utc(self.close_time),
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            is_closed=self.is_closed,
        )


@dataclass(slots=True)
class MarketUpdateResult:
    """Outcome of processing one candle update."""

    current_candle: Candle | None
    closed_candle: Candle | None
    emitted_new_closed_bar: bool
    ignored_update: bool = False
    reason: str | None = None


class CandleUpdateBuffer:
    """Buffers candle updates and emits a closed bar when the next bar arrives.

    Behavior:
    - multiple updates with the same close_time update the current in-progress bar
    - a strictly newer close_time closes the previous bar and becomes the new current bar
    - same or older already-closed bars are ignored safely
    """

    def __init__(self) -> None:
        self._current_candle: Candle | None = None
        self._last_emitted_close_time: datetime | None = None

    @property
    def current_candle(self) -> Candle | None:
        """Return the currently buffered in-progress candle."""

        return self._current_candle

    @property
    def last_emitted_close_time(self) -> datetime | None:
        """Return the latest candle close_time that has already been emitted as closed."""

        return self._last_emitted_close_time

    def process_update(self, candle_update: Candle) -> MarketUpdateResult:
        """Process one candle update and optionally emit the previous bar as closed."""

        update = candle_update.normalized()

        if self._current_candle is None:
            self._current_candle = _copy_candle(update, is_closed=False)
            return MarketUpdateResult(
                current_candle=self._current_candle,
                closed_candle=None,
                emitted_new_closed_bar=False,
            )

        current = self._current_candle
        if update.close_time == current.close_time:
            self._current_candle = _copy_candle(update, is_closed=False)
            return MarketUpdateResult(
                current_candle=self._current_candle,
                closed_candle=None,
                emitted_new_closed_bar=False,
            )

        if update.close_time < current.close_time:
            return MarketUpdateResult(
                current_candle=current,
                closed_candle=None,
                emitted_new_closed_bar=False,
                ignored_update=True,
                reason="out_of_order_update",
            )

        closed_candle = Candle(
            open_time=current.open_time,
            close_time=current.close_time,
            open=current.open,
            high=current.high,
            low=current.low,
            close=current.close,
            volume=current.volume,
            is_closed=True,
        )
        self._last_emitted_close_time = closed_candle.close_time
        self._current_candle = _copy_candle(update, is_closed=False)
        return MarketUpdateResult(
            current_candle=self._current_candle,
            closed_candle=closed_candle,
            emitted_new_closed_bar=True,
        )


def _copy_candle(candle: Candle, *, is_closed: bool) -> Candle:
    """Return a shallow candle copy with an explicit closed flag."""

    return Candle(
        open_time=candle.open_time,
        close_time=candle.close_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        is_closed=is_closed,
    )


class MarketStream(Protocol):
    """Protocol for a candle-producing market stream."""

    async def connect(self) -> None:
        """Open the market-data stream."""

    async def disconnect(self) -> None:
        """Close the market-data stream."""

    async def backfill(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        """Load startup candles before live processing begins."""

    async def next_candle(self) -> Candle:
        """Return the next closed candle from the stream."""
