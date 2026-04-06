"""Startup/bootstrap layer for the local v1 dry_run runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from bot.config import BotMode, LiveStartPolicy, Settings, load_settings
from bot.data.candle_clock import CandleClock
from bot.data.market_stream import CandleUpdateBuffer
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.execution.dry_run_executor import DryRunExecutor
from bot.execution.order_manager import OrderManager
from bot.runner.orchestrator import DryRunOrchestrator
from bot.storage.models import BotState, InstrumentConstraints
from bot.utils.rounding import OrderNormalizer


class BootstrapStorageProtocol(Protocol):
    """Minimal storage API required for dry_run bootstrap."""

    async def init_db(self) -> None:
        """Initialize storage schema."""

    async def load_bot_state(self, mode: BotMode, symbol: str, timeframe: str) -> BotState | None:
        """Load a previously stored runtime state."""


@dataclass(slots=True)
class DryRunStack:
    """All local components required to run one dry_run pipeline."""

    settings: Settings
    storage: BootstrapStorageProtocol
    runtime_state: BotState
    constraints: InstrumentConstraints
    buffer: CandleUpdateBuffer
    clock: CandleClock
    strategy_engine: StrategyEngine
    executor: DryRunExecutor
    orchestrator: DryRunOrchestrator


def build_initial_state(*, settings: Settings) -> BotState:
    """Return a clean runtime state for dry_run startup."""

    return BotState(
        mode=settings.mode,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
    )


async def restore_or_initialize_state(
    *,
    settings: Settings,
    storage: BootstrapStorageProtocol,
) -> BotState:
    """Return a runtime state according to the configured reset/restore policy."""

    if settings.mode != BotMode.DRY_RUN:
        raise ValueError("Only dry_run bootstrap is supported in v1.")

    if settings.live_start_policy == LiveStartPolicy.RESET:
        return build_initial_state(settings=settings)

    if settings.live_start_policy == LiveStartPolicy.RESTORE:
        restored = await storage.load_bot_state(
            mode=settings.mode,
            symbol=settings.symbol,
            timeframe=settings.timeframe,
        )
        if restored is not None:
            return restored
        return build_initial_state(settings=settings)

    raise ValueError("Only reset and restore policies are supported for local dry_run bootstrap in v1.")


def build_default_constraints(*, settings: Settings) -> InstrumentConstraints:
    """Return local placeholder constraints for dry_run bootstrap."""

    return InstrumentConstraints(
        symbol=settings.symbol,
        tick_size=0.1,
        lot_step=0.001,
        min_qty=0.01,
        min_notional=10.0,
        price_precision=1,
        qty_precision=3,
    )


def create_orchestrator(
    *,
    settings: Settings,
    storage: BootstrapStorageProtocol,
    runtime_state: BotState,
    constraints: InstrumentConstraints,
) -> DryRunOrchestrator:
    """Assemble the dry_run orchestrator and all local in-process components."""

    buffer = CandleUpdateBuffer()
    clock = CandleClock(
        timeframe=settings.timeframe,
        anchor_mode=settings.even_bar_anchor_mode,
        fixed_timestamp=settings.even_bar_fixed_timestamp,
    )
    strategy_engine = StrategyEngine()
    executor = DryRunExecutor(
        risk_manager=RiskManager(settings),
        order_manager=OrderManager(),
        position_manager=PositionManager(),
        order_normalizer=OrderNormalizer(settings.invalid_order_policy),
    )
    return DryRunOrchestrator(
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        runtime_state=runtime_state,
        storage=storage,
        candle_buffer=buffer,
        candle_clock=clock,
        strategy_engine=strategy_engine,
        executor=executor,
        constraints=constraints,
    )


async def build_dry_run_stack(
    *,
    settings: Settings | None = None,
    storage: BootstrapStorageProtocol | None = None,
) -> DryRunStack:
    """Build a complete local dry_run stack without network calls."""

    resolved_settings = settings or load_settings()
    if resolved_settings.mode != BotMode.DRY_RUN:
        raise ValueError("build_dry_run_stack() supports only MODE=dry_run in v1.")

    resolved_storage = storage
    if resolved_storage is None:
        from bot.storage.storage import SQLiteStorage

        resolved_storage = SQLiteStorage(resolved_settings.sqlite_db_path)

    await resolved_storage.init_db()
    runtime_state = await restore_or_initialize_state(settings=resolved_settings, storage=resolved_storage)
    constraints = build_default_constraints(settings=resolved_settings)
    orchestrator = create_orchestrator(
        settings=resolved_settings,
        storage=resolved_storage,
        runtime_state=runtime_state,
        constraints=constraints,
    )
    return DryRunStack(
        settings=resolved_settings,
        storage=resolved_storage,
        runtime_state=runtime_state,
        constraints=constraints,
        buffer=orchestrator.candle_buffer,
        clock=orchestrator.candle_clock,
        strategy_engine=orchestrator.strategy_engine,
        executor=orchestrator.executor,
        orchestrator=orchestrator,
    )


async def run_local_bootstrap() -> DryRunStack:
    """Build and return the local dry_run stack."""

    return await build_dry_run_stack()


def main() -> None:
    """Run the local dry_run bootstrap and print a short readiness message."""

    stack = asyncio.run(run_local_bootstrap())
    print(
        "dry_run bootstrap ready",
        stack.settings.symbol,
        stack.settings.timeframe,
        stack.runtime_state.pos_size_abs,
    )


if __name__ == "__main__":
    main()
