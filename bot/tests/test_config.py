"""Tests for settings loading and validation."""

from __future__ import annotations

import textwrap

import pytest

from bot.config import BotMode, DesyncPolicy, EvenBarAnchorMode, InvalidOrderPolicy, load_settings


def test_load_settings_from_env_file(tmp_path) -> None:
    """Settings should be loaded with typed values from a dotenv file."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        textwrap.dedent(
            """
            MODE=backtest
            SYMBOL=ETH-USDT
            TIMEFRAME=5m
            STARTUP_CANDLES_BACKFILL=123
            ENABLE_EVEN_BAR_FILTER=false
            EVEN_BAR_ANCHOR_MODE=utc_day_start
            DESYNC_POLICY=safe_stop
            INVALID_ORDER_POLICY=adjust
            TELEGRAM_ENABLED=false
            """
        ).strip(),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file, environ={})

    assert settings.mode == BotMode.BACKTEST
    assert settings.symbol == "ETH-USDT"
    assert settings.timeframe == "5m"
    assert settings.startup_candles_backfill == 123
    assert settings.enable_even_bar_filter is False
    assert settings.even_bar_anchor_mode == EvenBarAnchorMode.UTC_DAY_START
    assert settings.desync_policy == DesyncPolicy.SAFE_STOP
    assert settings.invalid_order_policy == InvalidOrderPolicy.ADJUST
    assert settings.telegram_enabled is False


def test_load_settings_rejects_invalid_mode(tmp_path) -> None:
    """Only backtest, dry_run, and live should be accepted as runtime modes."""

    env_file = tmp_path / ".env"
    env_file.write_text("MODE=paper", encoding="utf-8")

    with pytest.raises(ValueError, match="MODE"):
        load_settings(env_file=env_file, environ={})
