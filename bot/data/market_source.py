"""Application-friendly read-only market-data source built on top of the BingX client."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.data.market_stream import Candle
from bot.exchange.bingx_client import BingXClient, BingXHistoricalCandle
from bot.storage.models import InstrumentConstraints
from bot.utils.time_utils import ensure_utc


class BingXMarketSource:
    """Read-only source that converts BingX transport payloads into internal candle models."""

    def __init__(self, client: BingXClient) -> None:
        self.client = client

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        """Fetch internal constraints for one symbol."""

        return await self.client.fetch_instrument_constraints(symbol)

    async def fetch_startup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        """Fetch and normalize the latest startup candles for dry_run/backfill usage."""

        raw_candles = await self.client.fetch_historical_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        normalized = [self._to_internal_candle(item) for item in raw_candles]
        ordered = sorted(normalized, key=lambda candle: candle.close_time)
        deduplicated: dict[datetime, Candle] = {candle.close_time: candle for candle in ordered}
        return list(deduplicated.values())[-limit:]

    @staticmethod
    def _to_internal_candle(raw: BingXHistoricalCandle) -> Candle:
        """Convert a typed BingX historical candle into the shared internal candle model."""

        return Candle(
            open_time=_ms_to_utc(raw.open_time_ms),
            close_time=_ms_to_utc(raw.close_time_ms),
            open=raw.open,
            high=raw.high,
            low=raw.low,
            close=raw.close,
            volume=raw.volume,
            is_closed=True,
        )


def _ms_to_utc(value: int) -> datetime:
    """Convert exchange millisecond timestamps into UTC-aware datetimes."""

    return ensure_utc(datetime.fromtimestamp(value / 1000, tz=timezone.utc))
