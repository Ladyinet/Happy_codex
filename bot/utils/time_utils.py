"""UTC-only datetime helpers for v1."""

from __future__ import annotations

from datetime import datetime, timezone


SUPPORTED_TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def now_utc() -> datetime:
    """Return the current UTC-aware datetime."""

    return datetime.now(tz=timezone.utc)


def utc_now() -> datetime:
    """Backward-compatible alias for the shared UTC clock."""

    return now_utc()


def ensure_utc(dt: datetime) -> datetime:
    """Return a datetime converted to UTC and reject naive values."""

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Naive datetime values are not allowed in internal UTC logic.")
    return dt.astimezone(timezone.utc)


def datetime_to_iso(dt: datetime) -> str:
    """Serialize a datetime to a stable UTC ISO 8601 string."""

    return ensure_utc(dt).isoformat()


def datetime_from_iso(value: str) -> datetime:
    """Deserialize an ISO 8601 datetime string and normalize it to UTC."""

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)


def utc_day_start(dt: datetime) -> datetime:
    """Return the UTC midnight anchor for the day of the given datetime."""

    utc_dt = ensure_utc(dt)
    return utc_dt.replace(hour=0, minute=0, second=0, microsecond=0)


def timeframe_to_seconds(timeframe: str) -> int:
    """Convert supported timeframe strings into seconds."""

    try:
        return SUPPORTED_TIMEFRAMES[timeframe]
    except KeyError as exc:
        allowed = ", ".join(SUPPORTED_TIMEFRAMES)
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Allowed values: {allowed}.") from exc
