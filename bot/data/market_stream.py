"""Streaming interfaces for market data."""

from __future__ import annotations

from typing import Protocol

from bot.engine.signals import Candle


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
