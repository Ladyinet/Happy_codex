"""Tests for the runtime/service composition layer in bot.app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from bot.app import (
    APP_RUNTIME_DRY_RUN_ONLY,
    APP_RUNTIME_DRY_RUN_WITH_TELEGRAM,
    APP_RUNTIME_TELEGRAM_ONLY,
    AppLaunchError,
    build_app_context,
    build_telegram_service,
    resolve_app_runtime_mode,
    run_dry_run_only,
    run_dry_run_with_telegram,
    run_telegram_only,
)
from bot.config import BotMode, EvenBarAnchorMode, LiveStartPolicy, Settings
from bot.data.market_stream import Candle
from bot.storage.models import BotState, InstrumentConstraints


@dataclass
class FakeStorage:
    """Minimal storage used by app-layer tests."""

    restored_state: BotState | None = None
    init_db_calls: int = 0

    async def init_db(self) -> None:
        self.init_db_calls += 1

    async def load_bot_state(self, mode, symbol: str, timeframe: str) -> BotState | None:
        return self.restored_state

    async def save_bot_state(self, state: BotState) -> None:
        self.restored_state = state

    async def save_order(self, order) -> None:
        pass

    async def save_fill(self, fill) -> None:
        pass

    async def save_event(self, event) -> None:
        pass

    async def save_safe_stop_reason(self, record) -> None:
        pass

    async def add_subscriber(self, subscriber) -> None:
        pass

    async def deactivate_subscriber(self, chat_id: int) -> None:
        pass

    async def list_active_subscribers(self):
        return []


class FakeMarketSource:
    """Read-only market source stub for dry_run bootstrap tests."""

    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.constraints_calls = 0
        self.candles_calls = 0

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        self.constraints_calls += 1
        return InstrumentConstraints(
            symbol=symbol,
            tick_size=0.1,
            lot_step=0.0001,
            min_qty=0.0001,
            min_notional=2.0,
            price_precision=1,
            qty_precision=4,
        )

    async def fetch_startup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.candles_calls += 1
        return self.candles[-limit:]


@dataclass
class FakeController:
    """Simple controller stub returned by injected builders."""

    storage: FakeStorage
    state_provider: object


def _settings(*, telegram_enabled: bool = True, token: str | None = "token") -> Settings:
    return Settings(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        live_start_policy=LiveStartPolicy.RESET,
        startup_candles_backfill=2,
        even_bar_anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
        even_bar_fixed_timestamp="2026-04-12T12:01:00+00:00",
        telegram_enabled=telegram_enabled,
        telegram_bot_token=token,
    )


def _restored_state() -> BotState:
    return BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=0.15,
        avg_price=68000.0,
        last_candle_time=datetime(2026, 4, 12, 12, 1, tzinfo=timezone.utc),
    )


def _candle(open_minute: int, close_minute: int, close: float) -> Candle:
    return Candle(
        open_time=datetime(2026, 4, 12, 12, open_minute, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 12, 12, close_minute, tzinfo=timezone.utc),
        open=close - 1,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
        is_closed=True,
    )


def _state_provider_builder(**kwargs):
    runtime_state_getter = kwargs.get("runtime_state_getter")
    storage = kwargs["storage"]

    async def _provider():
        runtime_state = runtime_state_getter() if runtime_state_getter is not None else None
        if runtime_state is not None:
            return runtime_state
        restored = await storage.load_bot_state(None, "BTC-USDT", "1m")
        if restored is not None:
            return restored
        return BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")

    return _provider


def _controller_builder(**kwargs):
    return FakeController(storage=kwargs["storage"], state_provider=kwargs["state_provider"])


def _polling_runner_builder(**kwargs):
    async def _runner() -> bool:
        _polling_runner_builder.calls += 1
        _polling_runner_builder.last_kwargs = kwargs
        return True

    return _runner


_polling_runner_builder.calls = 0
_polling_runner_builder.last_kwargs = None


def test_resolve_app_runtime_mode_from_env() -> None:
    mode = resolve_app_runtime_mode(environ={"APP_RUNTIME_MODE": APP_RUNTIME_TELEGRAM_ONLY})
    assert mode == APP_RUNTIME_TELEGRAM_ONLY


@pytest.mark.asyncio
async def test_build_app_context_does_not_require_trading_endpoints() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])

    context = await build_app_context(
        settings=_settings(telegram_enabled=False, token=None),
        app_runtime_mode=APP_RUNTIME_DRY_RUN_ONLY,
        storage=storage,
        market_source=market_source,
    )

    assert context.dry_run_service is not None
    assert context.dry_run_service.stack.constraints.symbol == "BTC-USDT"
    assert market_source.constraints_calls == 1
    assert market_source.candles_calls == 1


@pytest.mark.asyncio
async def test_run_dry_run_only_builds_warmed_up_stack() -> None:
    storage = FakeStorage()
    market_source = FakeMarketSource([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])

    context = await run_dry_run_only(
        settings=_settings(telegram_enabled=False, token=None),
        storage=storage,
        market_source=market_source,
    )

    assert context.dry_run_service is not None
    assert context.dry_run_service.stack.startup_candles_loaded == 2
    assert context.dry_run_service.stack.runtime_state.last_candle_time == datetime(2026, 4, 12, 12, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_build_telegram_service_creates_polling_stack_without_dry_run_pipeline() -> None:
    storage = FakeStorage(restored_state=_restored_state())

    service = await build_telegram_service(
        settings=_settings(),
        storage=storage,
        state_provider_builder=_state_provider_builder,
        controller_builder=_controller_builder,
        polling_runner_builder=_polling_runner_builder,
    )

    assert service.enabled is True
    assert service.controller is not None
    assert service.polling_runner is not None


@pytest.mark.asyncio
async def test_run_telegram_only_starts_polling_without_dry_run_service() -> None:
    _polling_runner_builder.calls = 0
    storage = FakeStorage(restored_state=_restored_state())

    context = await run_telegram_only(
        settings=_settings(),
        storage=storage,
        state_provider_builder=_state_provider_builder,
        controller_builder=_controller_builder,
        polling_runner_builder=_polling_runner_builder,
    )

    assert context.dry_run_service is None
    assert context.telegram_service is not None
    assert _polling_runner_builder.calls == 1


@pytest.mark.asyncio
async def test_run_dry_run_with_telegram_builds_both_services() -> None:
    _polling_runner_builder.calls = 0
    storage = FakeStorage()
    market_source = FakeMarketSource([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])

    context = await run_dry_run_with_telegram(
        settings=_settings(),
        storage=storage,
        market_source=market_source,
        state_provider_builder=_state_provider_builder,
        controller_builder=_controller_builder,
        polling_runner_builder=_polling_runner_builder,
    )

    assert context.dry_run_service is not None
    assert context.telegram_service is not None
    assert _polling_runner_builder.calls == 1


@pytest.mark.asyncio
async def test_telegram_enabled_false_is_handled_clearly() -> None:
    storage = FakeStorage(restored_state=_restored_state())

    with pytest.raises(AppLaunchError, match="requires TELEGRAM_ENABLED=true"):
        await run_telegram_only(
            settings=_settings(telegram_enabled=False, token=None),
            storage=storage,
            state_provider_builder=_state_provider_builder,
            controller_builder=_controller_builder,
            polling_runner_builder=_polling_runner_builder,
        )


@pytest.mark.asyncio
async def test_missing_telegram_token_raises_clear_error() -> None:
    storage = FakeStorage(restored_state=_restored_state())

    with pytest.raises(AppLaunchError, match="TELEGRAM_BOT_TOKEN is required"):
        await run_telegram_only(
            settings=_settings(telegram_enabled=True, token=None),
            storage=storage,
            state_provider_builder=_state_provider_builder,
            controller_builder=_controller_builder,
            polling_runner_builder=_polling_runner_builder,
        )


@pytest.mark.asyncio
async def test_app_launcher_does_not_change_trading_state_directly() -> None:
    storage = FakeStorage(restored_state=_restored_state())
    market_source = FakeMarketSource([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])
    before = storage.restored_state.pos_size_abs if storage.restored_state is not None else 0.0

    context = await build_app_context(
        settings=_settings(),
        app_runtime_mode=APP_RUNTIME_DRY_RUN_WITH_TELEGRAM,
        storage=storage,
        market_source=market_source,
        state_provider_builder=_state_provider_builder,
        controller_builder=_controller_builder,
        polling_runner_builder=_polling_runner_builder,
    )

    after = context.dry_run_service.stack.runtime_state.pos_size_abs if context.dry_run_service is not None else 0.0
    assert before == after
