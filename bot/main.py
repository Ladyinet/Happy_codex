"""Startup/bootstrap layer for the local v1 dry_run runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from bot.config import BotMode, LiveStartPolicy, Settings, load_settings
from bot.data.candle_clock import CandleClock
from bot.data.market_source import BingXMarketSource
from bot.data.market_stream import CandleUpdateBuffer
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.exchange.bingx_client import BingXClient
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


class BootstrapMarketSourceProtocol(Protocol):
    """Minimal read-only market-source API required for dry_run bootstrap."""

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        """Return instrument constraints for the startup symbol."""

    async def fetch_startup_candles(self, symbol: str, timeframe: str, limit: int):
        """Return startup candles in the internal candle format."""


class BootstrapError(RuntimeError):
    """Raised when the dry_run bootstrap cannot fetch required read-only market data."""


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
    startup_candles_loaded: int = 0

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
    market_source: BootstrapMarketSourceProtocol | None = None,
) -> DryRunStack:
    """Build a complete dry_run stack with read-only startup market data."""

    resolved_settings = settings or load_settings()
    if resolved_settings.mode != BotMode.DRY_RUN:
        raise ValueError("build_dry_run_stack() supports only MODE=dry_run in v1.")

    resolved_storage = storage
    if resolved_storage is None:
        from bot.storage.storage import SQLiteStorage

        resolved_storage = SQLiteStorage(resolved_settings.sqlite_db_path)

    await resolved_storage.init_db()
    runtime_state = await restore_or_initialize_state(settings=resolved_settings, storage=resolved_storage)
    constraints, startup_candles = await fetch_startup_market_snapshot(
        settings=resolved_settings,
        market_source=market_source,
    )
    orchestrator = create_orchestrator(
        settings=resolved_settings,
        storage=resolved_storage,
        runtime_state=runtime_state,
        constraints=constraints,
    )
    startup_candles_loaded = await orchestrator.warmup_from_candles(startup_candles)
    return DryRunStack(
        settings=resolved_settings,
        storage=resolved_storage,
        runtime_state=orchestrator.runtime_state,
        constraints=constraints,
        buffer=orchestrator.candle_buffer,
        clock=orchestrator.candle_clock,
        strategy_engine=orchestrator.strategy_engine,
        executor=orchestrator.executor,
        orchestrator=orchestrator,
        startup_candles_loaded=startup_candles_loaded,
    )


async def run_local_bootstrap() -> DryRunStack:
    """Build and return the local dry_run stack."""

    return await build_dry_run_stack()


def main() -> None:
    """Run the local dry_run bootstrap and print a short readiness message."""

    stack = asyncio.run(run_local_bootstrap())
    print(
        f"mode={stack.settings.mode.value}",
        f"symbol={stack.settings.symbol}",
        f"timeframe={stack.settings.timeframe}",
        f"startup_candles_loaded={stack.startup_candles_loaded}",
        f"last_candle_time={stack.runtime_state.last_candle_time.isoformat() if stack.runtime_state.last_candle_time else 'none'}",
    )


async def fetch_startup_market_snapshot(
    *,
    settings: Settings,
    market_source: BootstrapMarketSourceProtocol | None = None,
) -> tuple[InstrumentConstraints, list]:
    """Fetch real startup constraints and historical candles for dry_run bootstrap."""

    if market_source is not None:
        return await _fetch_from_market_source(settings=settings, market_source=market_source)

    async with BingXClient(testnet=settings.bingx_testnet) as client:
        return await _fetch_from_market_source(
            settings=settings,
            market_source=BingXMarketSource(client),
        )


async def _fetch_from_market_source(
    *,
    settings: Settings,
    market_source: BootstrapMarketSourceProtocol,
) -> tuple[InstrumentConstraints, list]:
    try:
        constraints = await market_source.fetch_instrument_constraints(settings.symbol)
    except Exception as exc:
        raise BootstrapError(f"Failed to fetch instrument constraints for {settings.symbol}: {exc}") from exc

    try:
        startup_candles = await market_source.fetch_startup_candles(
            settings.symbol,
            settings.timeframe,
            settings.startup_candles_backfill,
        )
    except Exception as exc:
        raise BootstrapError(
            f"Failed to fetch startup candles for {settings.symbol} {settings.timeframe}: {exc}"
        ) from exc

    return constraints, startup_candles


if __name__ == "__main__":
    main()
