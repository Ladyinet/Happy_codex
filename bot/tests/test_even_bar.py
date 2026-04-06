"""Tests for the even-bar clock."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.config import EvenBarAnchorMode, Settings
from bot.data.candle_clock import CandleClock


def test_even_bar_default_is_utc_day_start() -> None:
    """The default even-bar anchor must remain utc_day_start."""

    assert Settings().even_bar_anchor_mode == EvenBarAnchorMode.UTC_DAY_START


def test_utc_day_start_anchor_even_and_odd_bars() -> None:
    """UTC day start anchor should alternate allowed bars deterministically."""

    clock = CandleClock(timeframe="1m", anchor_mode=EvenBarAnchorMode.UTC_DAY_START)
    bar0 = datetime(2026, 4, 6, 0, 0, tzinfo=timezone.utc)
    bar1 = datetime(2026, 4, 6, 0, 1, tzinfo=timezone.utc)
    bar2 = datetime(2026, 4, 6, 0, 2, tzinfo=timezone.utc)

    assert clock.bars_from_anchor(bar0) == 0
    assert clock.is_bar_allowed(bar0) is True
    assert clock.bars_from_anchor(bar1) == 1
    assert clock.is_bar_allowed(bar1) is False
    assert clock.bars_from_anchor(bar2) == 2
    assert clock.is_bar_allowed(bar2) is True


def test_fixed_timestamp_anchor() -> None:
    """Fixed timestamp anchor should use the provided UTC point as the reference."""

    clock = CandleClock(
        timeframe="1m",
        anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
        fixed_timestamp="2026-04-06T12:00:00+00:00",
    )
    bar = datetime(2026, 4, 6, 12, 3, tzinfo=timezone.utc)

    assert clock.bars_from_anchor(bar) == 3
    assert clock.is_bar_allowed(bar) is False


def test_live_start_anchor() -> None:
    """Live-start anchor should count bars from the provided live start time."""

    live_start = datetime(2026, 4, 6, 9, 30, tzinfo=timezone.utc)
    clock = CandleClock(
        timeframe="5m",
        anchor_mode=EvenBarAnchorMode.LIVE_START,
        live_start_time=live_start,
    )
    bar = datetime(2026, 4, 6, 9, 40, tzinfo=timezone.utc)

    assert clock.bars_from_anchor(bar) == 2
    assert clock.is_bar_allowed(bar) is True
