"""Tests for the local Telegram polling launcher script."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest

from bot.app import APP_RUNTIME_TELEGRAM_ONLY, AppContext, TelegramService
from bot.config import BotMode, Settings
from bot.storage.models import BotState


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_telegram_polling.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_telegram_polling_script_module", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@dataclass
class DummyStorage:
    """Minimal storage placeholder for script-level tests."""

    state: BotState


def _settings(*, enabled: bool = True, token: str | None = "token") -> Settings:
    return Settings(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        telegram_enabled=enabled,
        telegram_bot_token=token,
    )


def _context(*, settings: Settings, polling_runner=None) -> AppContext:
    async def _default_runner() -> bool:
        return True

    return AppContext(
        settings=settings,
        storage=DummyStorage(state=BotState(mode=settings.mode, symbol=settings.symbol, timeframe=settings.timeframe)),
        app_runtime_mode=APP_RUNTIME_TELEGRAM_ONLY,
        dry_run_service=None,
        telegram_service=TelegramService(
            enabled=settings.telegram_enabled,
            state_provider=None,
            controller=object(),
            polling_runner=polling_runner or _default_runner,
        ),
    )


@pytest.mark.asyncio
async def test_script_returns_clear_error_when_telegram_disabled(capsys) -> None:
    module = _load_script_module()

    code = await module.run_telegram_polling_script(settings=_settings(enabled=False, token=None))

    captured = capsys.readouterr()
    assert code == 1
    assert "TELEGRAM_ENABLED=true" in captured.err


@pytest.mark.asyncio
async def test_script_returns_clear_error_when_token_missing(capsys) -> None:
    module = _load_script_module()

    code = await module.run_telegram_polling_script(settings=_settings(enabled=True, token=None))

    captured = capsys.readouterr()
    assert code == 1
    assert "TELEGRAM_BOT_TOKEN is required" in captured.err


@pytest.mark.asyncio
async def test_script_uses_context_builder_without_bingx_trading_dependencies(capsys) -> None:
    module = _load_script_module()

    async def build_context(*, settings: Settings):
        return _context(settings=settings)

    code = await module.run_telegram_polling_script(
        settings=_settings(),
        build_context=build_context,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "app_runtime_mode: telegram_only" in captured.out
    assert "state_source: storage snapshot" in captured.out


@pytest.mark.asyncio
async def test_script_uses_telegram_runner_and_does_not_duplicate_polling_logic() -> None:
    module = _load_script_module()
    calls = {"count": 0}

    async def polling_runner() -> bool:
        calls["count"] += 1
        return True

    async def build_context(*, settings: Settings):
        return _context(settings=settings, polling_runner=polling_runner)

    code = await module.run_telegram_polling_script(
        settings=_settings(),
        build_context=build_context,
    )

    assert code == 0
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_script_does_not_change_trading_state_directly() -> None:
    module = _load_script_module()
    state = BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m", pos_size_abs=0.25)

    async def polling_runner() -> bool:
        return True

    async def build_context(*, settings: Settings):
        return AppContext(
            settings=settings,
            storage=DummyStorage(state=state),
            app_runtime_mode=APP_RUNTIME_TELEGRAM_ONLY,
            dry_run_service=None,
            telegram_service=TelegramService(
                enabled=True,
                state_provider=lambda: state,
                controller=object(),
                polling_runner=polling_runner,
            ),
        )

    before = state.pos_size_abs
    code = await module.run_telegram_polling_script(
        settings=_settings(),
        build_context=build_context,
    )
    after = state.pos_size_abs

    assert code == 0
    assert before == after
