"""Local read-only websocket runner for dry_run market updates."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.config import load_settings
from bot.data.market_ws import BingXMarketWebSocket, MarketWSError, build_kline_subscribe_message
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
    debug = True
    subscribe_payload = build_kline_subscribe_message(settings.symbol, settings.timeframe)
    print(f"debug_mode: {debug}")
    print(f"subscribe_payload: {subscribe_payload}")

    market_ws = BingXMarketWebSocket(testnet=settings.bingx_testnet)
    last_logged_close_time = None
    logged_updates = 0
    max_verbose_updates = 20

    async def _status_logger(message: str) -> None:
        print(f"ws_status: {message}")

    try:
        async for candle in market_ws.stream_candles(
            symbol=settings.symbol,
            timeframe=settings.timeframe,
            status_callback=_status_logger,
            debug=debug,
        ):
            pos_before = stack.orchestrator.runtime_state.pos_size_abs
            update_kind = _classify_update(
                current_buffer_candle=stack.buffer.current_candle,
                incoming_candle=candle,
            )
            step_result = await stack.orchestrator.process_candle_update(candle)
            orders_count = sum(1 for item in step_result.execution_results if item.order is not None)
            fills_count = sum(len(item.fills) for item in step_result.execution_results)
            pos_after = (
                step_result.runtime_state.pos_size_abs
                if step_result.runtime_state is not None
                else pos_before
            )
            close_time_changed = last_logged_close_time != candle.close_time
            should_log = close_time_changed or step_result.closed_bar_processed or logged_updates < max_verbose_updates
            if not should_log:
                continue

            logged_updates += 1
            last_logged_close_time = candle.close_time
            closed_bar_time = (
                datetime_to_iso(step_result.market_update.closed_candle.close_time)
                if step_result.market_update.closed_candle is not None
                else "n/a"
            )
            reason = _derive_no_execution_reason(step_result)
            print(
                "candle_update: "
                f"candle_close_time={datetime_to_iso(candle.close_time)} "
                f"candle_close_price={candle.close} "
                f"update_kind={update_kind}"
            )
            print(
                "pipeline_step: "
                f"processed_closed_bar={step_result.closed_bar_processed} "
                f"closed_bar_time={closed_bar_time} "
                f"execution_results_count={len(step_result.execution_results)} "
                f"orders_count={orders_count} "
                f"fills_count={fills_count} "
                f"pos_size_abs_before={pos_before} "
                f"pos_size_abs_after={pos_after}"
            )
            if reason is not None:
                print(f"pipeline_reason: {reason}")
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


def _classify_update(*, current_buffer_candle, incoming_candle) -> str:
    """Classify one parsed candle update relative to the current buffer state."""

    if current_buffer_candle is None:
        return "initial"
    if incoming_candle.close_time > current_buffer_candle.close_time:
        return "new_close_time"
    if incoming_candle.close_time == current_buffer_candle.close_time:
        return "current_update"
    return "duplicate_or_old"


def _derive_no_execution_reason(step_result) -> str | None:
    """Return a short human-readable reason when no execution happened."""

    if step_result.execution_results:
        return None
    if not step_result.closed_bar_processed:
        if step_result.market_update.ignored_update:
            return f"market update ignored: {step_result.market_update.reason or 'unknown'}"
        return "buffer did not emit a newly closed bar"

    decision = step_result.strategy_decision
    if decision is None:
        return "strategy decision is not available"
    if decision.safe_stop_required:
        return f"safe_stop_required: {decision.safe_stop_reason or 'no reason provided'}"
    if decision.blocked_by_even_bar:
        return "blocked by even-bar filter"
    if decision.blocked_by_tp_touch:
        return "blocked by TP-touch rule"
    if not decision.order_intents:
        return "strategy produced no order intents"
    return "no execution results were produced"


if __name__ == "__main__":
    main()
