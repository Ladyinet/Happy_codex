"""Local read-only websocket runner for dry_run market updates."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.config import load_settings
from bot.data.market_ws import BingXMarketWebSocket, MarketWSError
from bot.main import build_dry_run_stack
from bot.utils.time_utils import datetime_to_iso


async def _run() -> int:
    settings = load_settings(PROJECT_ROOT / ".env")
    stack = await build_dry_run_stack(settings=settings)

    print(f"mode: {stack.settings.mode.value}")
    print(f"symbol: {stack.settings.symbol}")
    print(f"timeframe: {stack.settings.timeframe}")
    print(f"startup_candles_loaded: {stack.startup_candles_loaded}")
    print(
        "last_candle_time: "
        f"{datetime_to_iso(stack.runtime_state.last_candle_time) if stack.runtime_state.last_candle_time else 'n/a'}"
    )

    market_ws = BingXMarketWebSocket(testnet=settings.bingx_testnet)

    async def _status_logger(message: str) -> None:
        print(f"ws_status: {message}")

    try:
        async for candle in market_ws.stream_candles(
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            status_callback=_status_logger,
        ):
            print(
                "candle_update_received: "
                f"close_time={datetime_to_iso(candle.close_time)} "
                f"close={candle.close} "
                f"is_closed={candle.is_closed}"
            )
            step_result = await stack.orchestrator.process_candle_update(candle)
            orders_count = sum(1 for item in step_result.execution_results if item.order is not None)
            fills_count = sum(len(item.fills) for item in step_result.execution_results)
            print(f"processed_closed_bar: {step_result.closed_bar_processed}")
            print(f"execution_results_count: {len(step_result.execution_results)}")
            print(f"orders_count: {orders_count}")
            print(f"fills_count: {fills_count}")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        label = "websocket runtime failed"
        if isinstance(exc, MarketWSError):
            label = "websocket reconnect failed"
        print(f"{label}: {exc}", file=sys.stderr)
        return 1

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
