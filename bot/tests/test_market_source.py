"""Tests for the read-only market source layer."""

from __future__ import annotations

from datetime import timezone

import pytest

from bot.data.market_source import BingXMarketSource
from bot.exchange.bingx_client import BingXHistoricalCandle
from bot.storage.models import InstrumentConstraints


class FakeBingXClient:
    """Simple fake client used by market-source tests."""

    def __init__(self, *, candles: list[BingXHistoricalCandle], constraints: InstrumentConstraints | None = None) -> None:
        self._candles = candles
        self._constraints = constraints or InstrumentConstraints(
            symbol="BTC-USDT",
            tick_size=0.1,
            lot_step=0.001,
            min_qty=0.01,
            min_notional=10.0,
            price_precision=1,
            qty_precision=3,
        )
        self.calls: list[tuple[str, str, int]] = []

    async def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int) -> list[BingXHistoricalCandle]:
        self.calls.append((symbol, timeframe, limit))
        return list(self._candles)

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        return self._constraints


def _raw_candle(open_time_ms: int, close_time_ms: int, close: float) -> BingXHistoricalCandle:
    return BingXHistoricalCandle(
        symbol="BTC-USDT",
        interval="1m",
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=10.0,
    )


@pytest.mark.asyncio
async def test_market_source_returns_candles_in_correct_order() -> None:
    client = FakeBingXClient(
        candles=[
            _raw_candle(1712731260000, 1712731320000, 101.5),
            _raw_candle(1712731200000, 1712731260000, 100.5),
        ]
    )
    source = BingXMarketSource(client)

    candles = await source.fetch_startup_candles("BTC-USDT", "1m", 2)

    assert [c.close for c in candles] == [100.5, 101.5]
    assert all(c.is_closed for c in candles)


@pytest.mark.asyncio
async def test_startup_backfill_returns_last_n_candles() -> None:
    client = FakeBingXClient(
        candles=[
            _raw_candle(1712731200000, 1712731260000, 100.5),
            _raw_candle(1712731260000, 1712731320000, 101.5),
            _raw_candle(1712731320000, 1712731380000, 102.5),
        ]
    )
    source = BingXMarketSource(client)

    candles = await source.fetch_startup_candles("BTC-USDT", "1m", 2)

    assert len(candles) == 2
    assert [c.close for c in candles] == [101.5, 102.5]


@pytest.mark.asyncio
async def test_market_source_enforces_utc_datetimes() -> None:
    client = FakeBingXClient(candles=[_raw_candle(1712731200000, 1712731260000, 100.5)])
    source = BingXMarketSource(client)

    candles = await source.fetch_startup_candles("BTC-USDT", "1m", 1)

    assert candles[0].open_time.tzinfo == timezone.utc
    assert candles[0].close_time.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_market_source_deduplicates_same_close_time() -> None:
    client = FakeBingXClient(
        candles=[
            _raw_candle(1712731200000, 1712731260000, 100.5),
            _raw_candle(1712731200000, 1712731260000, 100.7),
            _raw_candle(1712731260000, 1712731320000, 101.5),
        ]
    )
    source = BingXMarketSource(client)

    candles = await source.fetch_startup_candles("BTC-USDT", "1m", 5)

    assert len(candles) == 2
    assert candles[0].close == 100.7


@pytest.mark.asyncio
async def test_market_source_can_fetch_constraints() -> None:
    client = FakeBingXClient(candles=[])
    source = BingXMarketSource(client)

    constraints = await source.fetch_instrument_constraints("BTC-USDT")

    assert constraints.symbol == "BTC-USDT"
