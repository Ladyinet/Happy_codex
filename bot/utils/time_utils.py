"""Time helpers for the project skeleton."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=timezone.utc)


def timeframe_to_seconds(timeframe: str) -> int:
    """Convert a timeframe string into seconds."""
    raise NotImplementedError
