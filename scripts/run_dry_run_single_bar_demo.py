"""Local one-shot demo for dry_run bootstrap + warmup + one synthetic next bar."""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.config import load_settings
from bot.data.market_stream import Candle
from bot.main import build_dry_run_stack
from bot.utils.time_utils import datetime_to_iso, timeframe_to_seconds


async def _run() -> int:
    settings = load_settings(PROJECT_ROOT / ".env")
    stack = await build_dry_run_stack(settings=settings)

    current_candle = stack.buffer.current_candle
    if current_candle is None:
        print("dry_run single-bar demo failed: startup backfill returned no candles, current buffer is empty.", file=sys.stderr)
        return 1

    pos_before = stack.runtime_state.pos_size_abs
    print(f"mode: {stack.settings.mode.value}")
    print(f"symbol: {stack.settings.symbol}")
    print(f"timeframe: {stack.settings.timeframe}")
    print(f"startup_candles_loaded: {stack.startup_candles_loaded}")
    print(f"last_candle_time: {datetime_to_iso(stack.runtime_state.last_candle_time) if stack.runtime_state.last_candle_time else 'n/a'}")
    print(f"current_pos_size_abs_before_new_bar: {pos_before}")

    first_next_candle = _build_synthetic_next_candle(current_candle, timeframe=stack.settings.timeframe)
    first_result = await stack.orchestrator.process_candle_update(first_next_candle)
    _print_step_result(step=1, result=first_result, pos_before=pos_before)

    second_input_base = stack.buffer.current_candle or first_next_candle
    pos_before_second = stack.orchestrator.runtime_state.pos_size_abs
    second_next_candle = _build_synthetic_next_candle(second_input_base, timeframe=stack.settings.timeframe)
    second_result = await stack.orchestrator.process_candle_update(second_next_candle)
    _print_step_result(step=2, result=second_result, pos_before=pos_before_second)

    return 0


def _print_step_result(*, step: int, result, pos_before: float) -> None:
    processed_bar = result.market_update.closed_candle
    processed_bar_time = (
        datetime_to_iso(processed_bar.close_time)
        if processed_bar is not None
        else "n/a"
    )
    orders_count = sum(1 for item in result.execution_results if item.order is not None)
    fills_count = sum(len(item.fills) for item in result.execution_results)
    strategy_events_count = len(result.strategy_decision.events) if result.strategy_decision is not None else 0
    pos_after = result.runtime_state.pos_size_abs if result.runtime_state is not None else pos_before
    last_candle_after = (
        datetime_to_iso(result.runtime_state.last_candle_time)
        if result.runtime_state is not None and result.runtime_state.last_candle_time is not None
        else "n/a"
    )
    reason = _derive_no_execution_reason(result)

    print(f"step_{step}_close_time_processed_bar: {processed_bar_time}")
    print(f"step_{step}_even_bar_allowed: {result.even_bar_allowed}")
    print(f"step_{step}_processed_closed_bar: {result.closed_bar_processed}")
    print(f"step_{step}_execution_results_count: {len(result.execution_results)}")
    print(f"step_{step}_orders_count: {orders_count}")
    print(f"step_{step}_fills_count: {fills_count}")
    print(f"step_{step}_strategy_events_count: {strategy_events_count}")
    print(f"step_{step}_pos_size_abs_before: {pos_before}")
    print(f"step_{step}_pos_size_abs_after: {pos_after}")
    print(f"step_{step}_last_candle_time_after: {last_candle_after}")
    if reason is not None:
        print(f"step_{step}_reason: {reason}")


def _derive_no_execution_reason(result) -> str | None:
    if not result.closed_bar_processed:
        return "no newly closed bar was emitted by the buffer"
    if result.execution_results:
        return None
    decision = result.strategy_decision
    if decision is None:
        return "strategy decision is not available"
    if decision.safe_stop_required:
        return f"safe_stop_required: {decision.safe_stop_reason or 'no reason provided'}"
    if decision.blocked_by_even_bar:
        return "bar blocked by even-bar filter"
    if decision.blocked_by_tp_touch:
        return "DCA blocked by TP touch rule"
    if not decision.order_intents:
        return "strategy produced no order intents on this bar"
    return "no execution results were produced"


def _build_synthetic_next_candle(current_candle: Candle, *, timeframe: str) -> Candle:
    """Build one deterministic synthetic next candle above the last warmed-up candle."""

    timeframe_seconds = timeframe_to_seconds(timeframe)
    next_open_time = current_candle.close_time
    next_close_time = current_candle.close_time + timedelta(seconds=timeframe_seconds)
    base_close = current_candle.close
    synthetic_close = round(base_close * 1.0002, 8)
    synthetic_high = max(base_close, synthetic_close) * 1.0003
    synthetic_low = min(base_close, synthetic_close) * 0.9997

    return Candle(
        open_time=next_open_time,
        close_time=next_close_time,
        open=base_close,
        high=round(synthetic_high, 8),
        low=round(synthetic_low, 8),
        close=synthetic_close,
        volume=current_candle.volume,
        is_closed=False,
    )


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
