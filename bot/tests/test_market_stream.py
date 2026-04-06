"""Tests for the internal candle update buffer."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.data.market_stream import Candle, CandleUpdateBuffer


def _candle(minute: int, close: float, *, second: int = 0) -> Candle:
    open_time = datetime(2026, 4, 7, 12, minute, second, tzinfo=timezone.utc)
    close_time = datetime(2026, 4, 7, 12, minute + 1, second, tzinfo=timezone.utc)
    return Candle(
        open_time=open_time,
        close_time=close_time,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=10.0,
    )


def test_multiple_updates_for_same_bar_do_not_emit_closed_bar() -> None:
    """Several updates for the same candle must not emit a closed bar."""

    buffer = CandleUpdateBuffer()

    first = buffer.process_update(_candle(0, 100.0))
    second = buffer.process_update(_candle(0, 101.0))

    assert first.emitted_new_closed_bar is False
    assert second.emitted_new_closed_bar is False
    assert second.closed_candle is None
    assert second.current_candle is not None
    assert second.current_candle.close == 101.0
    assert second.current_candle.is_closed is False


def test_next_bar_arrival_closes_previous_bar() -> None:
    """When a newer bar arrives, the previous bar becomes closed."""

    buffer = CandleUpdateBuffer()
    buffer.process_update(_candle(0, 100.0))
    result = buffer.process_update(_candle(1, 105.0))

    assert result.emitted_new_closed_bar is True
    assert result.closed_candle is not None
    assert result.closed_candle.close_time == datetime(2026, 4, 7, 12, 1, tzinfo=timezone.utc)
    assert result.closed_candle.close == 100.0
    assert result.closed_candle.is_closed is True
    assert result.current_candle is not None
    assert result.current_candle.close == 105.0
    assert result.current_candle.is_closed is False


def test_same_close_time_is_not_new_bar() -> None:
    """Repeated updates with identical close_time must not count as a new bar."""

    buffer = CandleUpdateBuffer()
    first_update = _candle(0, 100.0)
    second_update = _candle(0, 102.0)

    buffer.process_update(first_update)
    result = buffer.process_update(second_update)

    assert result.emitted_new_closed_bar is False
    assert result.closed_candle is None
    assert result.ignored_update is False


def test_out_of_order_update_does_not_break_state() -> None:
    """Older updates must be ignored without modifying the current candle."""

    buffer = CandleUpdateBuffer()
    buffer.process_update(_candle(0, 100.0))
    buffer.process_update(_candle(1, 105.0))
    result = buffer.process_update(_candle(0, 99.0))

    assert result.ignored_update is True
    assert result.reason == "out_of_order_update"
    assert result.emitted_new_closed_bar is False
    assert result.current_candle is not None
    assert result.current_candle.close_time == datetime(2026, 4, 7, 12, 2, tzinfo=timezone.utc)


def test_all_buffer_datetimes_must_be_utc_aware() -> None:
    """Naive datetime inputs must be rejected by the update buffer."""

    buffer = CandleUpdateBuffer()
    naive_candle = Candle(
        open_time=datetime(2026, 4, 7, 12, 0),
        close_time=datetime(2026, 4, 7, 12, 1),
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=10.0,
    )

    try:
        buffer.process_update(naive_candle)
    except ValueError as exc:
        assert "Naive datetime" in str(exc)
    else:
        raise AssertionError("Expected ValueError for naive datetimes.")
