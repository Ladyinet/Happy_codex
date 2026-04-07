"""Local read-only smoke test for BingX market metadata and startup candles."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.config import load_settings
from bot.data.market_source import BingXMarketSource
from bot.exchange.bingx_client import BingXClient, BingXClientError, BingXPayloadError
from bot.exchange.metadata import BingXMetadataError
from bot.utils.time_utils import datetime_to_iso


async def _run() -> int:
    settings = load_settings(PROJECT_ROOT / ".env")

    try:
        async with BingXClient(testnet=settings.bingx_testnet) as client:
            market_source = BingXMarketSource(client)

            constraints = await market_source.fetch_instrument_constraints(settings.symbol)
            candles = await market_source.fetch_startup_candles(
                settings.symbol,
                settings.timeframe,
                5,
            )
    except (BingXClientError, BingXPayloadError, BingXMetadataError) as exc:
        print(f"BingX read-only smoke test failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected smoke test error: {exc}", file=sys.stderr)
        return 1

    first_close_time = datetime_to_iso(candles[0].close_time) if candles else "n/a"
    last_close_time = datetime_to_iso(candles[-1].close_time) if candles else "n/a"
    last_close_price = candles[-1].close if candles else "n/a"

    print(f"symbol: {settings.symbol}")
    print(f"tick_size: {constraints.tick_size}")
    print(f"lot_step: {constraints.lot_step}")
    print(f"min_qty: {constraints.min_qty}")
    print(f"min_notional: {constraints.min_notional}")
    print(f"candles_count: {len(candles)}")
    print(f"first_close_time: {first_close_time}")
    print(f"last_close_time: {last_close_time}")
    print(f"last_close_price: {last_close_price}")
    return 0


def main() -> None:
    """Run the local read-only BingX smoke test and exit with an explicit status code."""

    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
