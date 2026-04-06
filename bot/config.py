"""Configuration loading and validation for v1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping, TypeVar

from dotenv import dotenv_values


class BotMode(StrEnum):
    """Allowed runtime modes for the project."""

    BACKTEST = "backtest"
    DRY_RUN = "dry_run"
    LIVE = "live"


class TouchMode(StrEnum):
    """Explicit touch behavior for all strategy checks."""

    WICK = "wick"
    BODY = "body"
    CLOSE = "close"


class EvenBarAnchorMode(StrEnum):
    """Allowed anchor modes for the even-bar filter."""

    UTC_DAY_START = "utc_day_start"
    LIVE_START = "live_start"
    FIXED_TIMESTAMP = "fixed_timestamp"


class SubcoverConfirmMode(StrEnum):
    """Allowed confirmation modes for sub-cover logic."""

    OFF = "off"
    BREAKEVEN = "breakeven"
    SUBCOVER_TP = "subcover_tp"


class LiveStartPolicy(StrEnum):
    """Startup policy for live mode."""

    RESET = "reset"
    RESTORE = "restore"
    SYNC_ONLY = "sync_only"


class DesyncPolicy(StrEnum):
    """Policy for exchange and local-state desynchronization."""

    SAFE_STOP = "safe_stop"
    REBUILD_FROM_EXCHANGE = "rebuild_from_exchange"
    MANUAL_CONFIRM = "manual_confirm"


class InvalidOrderPolicy(StrEnum):
    """Policy for invalid orders after normalization."""

    ADJUST = "adjust"
    SKIP = "skip"
    SAFE_STOP = "safe_stop"


class ApiBackoffMode(StrEnum):
    """Retry backoff policy for API failures."""

    EXPONENTIAL = "exponential"


EnumT = TypeVar("EnumT", bound=StrEnum)


@dataclass(slots=True)
class Settings:
    """Typed configuration container."""

    bingx_api_key: str | None = None
    bingx_api_secret: str | None = None
    bingx_testnet: bool = False
    mode: BotMode = BotMode.DRY_RUN
    symbol: str = "BTC-USDT"
    timeframe: str = "1m"
    startup_candles_backfill: int = 300
    first_sell_qty_coin: float = 0.09
    use_equity_pct_base: bool = False
    base_order_pct_eq: float = 0.0
    equity_for_sizing_usdt: float = 100.0
    tp_percent: float = 1.1
    callback_percent: float = 0.2
    sub_sell_tp_percent: float = 1.3
    margin_call_limit: int = 244
    block_dca_on_tp_touch: bool = True
    require_close_below_full_tp: bool = True
    touch_mode: TouchMode = TouchMode.WICK
    subcover_confirm_mode: SubcoverConfirmMode = SubcoverConfirmMode.SUBCOVER_TP
    enable_even_bar_filter: bool = True
    even_bar_anchor_mode: EvenBarAnchorMode = EvenBarAnchorMode.UTC_DAY_START
    even_bar_fixed_timestamp: str | None = None
    max_orders_per_3min: int = 14
    max_dca_per_bar: int = 6
    max_subcover_per_bar: int = 10
    live_start_policy: LiveStartPolicy = LiveStartPolicy.RESET
    desync_policy: DesyncPolicy = DesyncPolicy.SAFE_STOP
    invalid_order_policy: InvalidOrderPolicy = InvalidOrderPolicy.ADJUST
    api_max_retries: int = 3
    api_backoff_base_seconds: int = 1
    api_backoff_mode: ApiBackoffMode = ApiBackoffMode.EXPONENTIAL
    telegram_bot_token: str | None = None
    telegram_enabled: bool = True
    telegram_max_messages_per_second: int = 10
    sqlite_db_path: str = "bot_state.db"
    log_level: str = "INFO"
    log_file: str = "bot.log"

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        environ: Mapping[str, str | None] | None = None,
    ) -> "Settings":
        """Build settings from a dotenv file and environment variables."""

        raw = _load_raw_values(env_file=env_file, environ=environ)
        settings = cls(
            bingx_api_key=_parse_optional_str(raw.get("BINGX_API_KEY")),
            bingx_api_secret=_parse_optional_str(raw.get("BINGX_API_SECRET")),
            bingx_testnet=_parse_bool(raw.get("BINGX_TESTNET"), default=False, field_name="BINGX_TESTNET"),
            mode=_parse_enum(raw.get("MODE"), BotMode, field_name="MODE", default=BotMode.DRY_RUN),
            symbol=_parse_required_str(raw.get("SYMBOL"), default="BTC-USDT", field_name="SYMBOL"),
            timeframe=_parse_required_str(raw.get("TIMEFRAME"), default="1m", field_name="TIMEFRAME"),
            startup_candles_backfill=_parse_int(
                raw.get("STARTUP_CANDLES_BACKFILL"),
                default=300,
                field_name="STARTUP_CANDLES_BACKFILL",
            ),
            first_sell_qty_coin=_parse_float(
                raw.get("FIRST_SELL_QTY_COIN"),
                default=0.09,
                field_name="FIRST_SELL_QTY_COIN",
            ),
            use_equity_pct_base=_parse_bool(
                raw.get("USE_EQUITY_PCT_BASE"),
                default=False,
                field_name="USE_EQUITY_PCT_BASE",
            ),
            base_order_pct_eq=_parse_float(
                raw.get("BASE_ORDER_PCT_EQ"),
                default=0.0,
                field_name="BASE_ORDER_PCT_EQ",
            ),
            equity_for_sizing_usdt=_parse_float(
                raw.get("EQUITY_FOR_SIZING_USDT"),
                default=100.0,
                field_name="EQUITY_FOR_SIZING_USDT",
            ),
            tp_percent=_parse_float(raw.get("TP_PERCENT"), default=1.1, field_name="TP_PERCENT"),
            callback_percent=_parse_float(
                raw.get("CALLBACK_PERCENT"),
                default=0.2,
                field_name="CALLBACK_PERCENT",
            ),
            sub_sell_tp_percent=_parse_float(
                raw.get("SUB_SELL_TP_PERCENT"),
                default=1.3,
                field_name="SUB_SELL_TP_PERCENT",
            ),
            margin_call_limit=_parse_int(
                raw.get("MARGIN_CALL_LIMIT"),
                default=244,
                field_name="MARGIN_CALL_LIMIT",
            ),
            block_dca_on_tp_touch=_parse_bool(
                raw.get("BLOCK_DCA_ON_TP_TOUCH"),
                default=True,
                field_name="BLOCK_DCA_ON_TP_TOUCH",
            ),
            require_close_below_full_tp=_parse_bool(
                raw.get("REQUIRE_CLOSE_BELOW_FULL_TP"),
                default=True,
                field_name="REQUIRE_CLOSE_BELOW_FULL_TP",
            ),
            touch_mode=_parse_enum(raw.get("TOUCH_MODE"), TouchMode, field_name="TOUCH_MODE", default=TouchMode.WICK),
            subcover_confirm_mode=_parse_enum(
                raw.get("SUBCOVER_CONFIRM_MODE"),
                SubcoverConfirmMode,
                field_name="SUBCOVER_CONFIRM_MODE",
                default=SubcoverConfirmMode.SUBCOVER_TP,
            ),
            enable_even_bar_filter=_parse_bool(
                raw.get("ENABLE_EVEN_BAR_FILTER"),
                default=True,
                field_name="ENABLE_EVEN_BAR_FILTER",
            ),
            even_bar_anchor_mode=_parse_enum(
                raw.get("EVEN_BAR_ANCHOR_MODE"),
                EvenBarAnchorMode,
                field_name="EVEN_BAR_ANCHOR_MODE",
                default=EvenBarAnchorMode.UTC_DAY_START,
            ),
            even_bar_fixed_timestamp=_parse_optional_str(raw.get("EVEN_BAR_FIXED_TIMESTAMP")),
            max_orders_per_3min=_parse_int(
                raw.get("MAX_ORDERS_PER_3MIN"),
                default=14,
                field_name="MAX_ORDERS_PER_3MIN",
            ),
            max_dca_per_bar=_parse_int(raw.get("MAX_DCA_PER_BAR"), default=6, field_name="MAX_DCA_PER_BAR"),
            max_subcover_per_bar=_parse_int(
                raw.get("MAX_SUBCOVER_PER_BAR"),
                default=10,
                field_name="MAX_SUBCOVER_PER_BAR",
            ),
            live_start_policy=_parse_enum(
                raw.get("LIVE_START_POLICY"),
                LiveStartPolicy,
                field_name="LIVE_START_POLICY",
                default=LiveStartPolicy.RESET,
            ),
            desync_policy=_parse_enum(
                raw.get("DESYNC_POLICY"),
                DesyncPolicy,
                field_name="DESYNC_POLICY",
                default=DesyncPolicy.SAFE_STOP,
            ),
            invalid_order_policy=_parse_enum(
                raw.get("INVALID_ORDER_POLICY"),
                InvalidOrderPolicy,
                field_name="INVALID_ORDER_POLICY",
                default=InvalidOrderPolicy.ADJUST,
            ),
            api_max_retries=_parse_int(raw.get("API_MAX_RETRIES"), default=3, field_name="API_MAX_RETRIES"),
            api_backoff_base_seconds=_parse_int(
                raw.get("API_BACKOFF_BASE_SECONDS"),
                default=1,
                field_name="API_BACKOFF_BASE_SECONDS",
            ),
            api_backoff_mode=_parse_enum(
                raw.get("API_BACKOFF_MODE"),
                ApiBackoffMode,
                field_name="API_BACKOFF_MODE",
                default=ApiBackoffMode.EXPONENTIAL,
            ),
            telegram_bot_token=_parse_optional_str(raw.get("TELEGRAM_BOT_TOKEN")),
            telegram_enabled=_parse_bool(
                raw.get("TELEGRAM_ENABLED"),
                default=True,
                field_name="TELEGRAM_ENABLED",
            ),
            telegram_max_messages_per_second=_parse_int(
                raw.get("TELEGRAM_MAX_MESSAGES_PER_SECOND"),
                default=10,
                field_name="TELEGRAM_MAX_MESSAGES_PER_SECOND",
            ),
            sqlite_db_path=_parse_required_str(
                raw.get("SQLITE_DB_PATH"),
                default="bot_state.db",
                field_name="SQLITE_DB_PATH",
            ),
            log_level=_parse_required_str(raw.get("LOG_LEVEL"), default="INFO", field_name="LOG_LEVEL"),
            log_file=_parse_required_str(raw.get("LOG_FILE"), default="bot.log", field_name="LOG_FILE"),
        )
        _validate_settings(settings)
        return settings


def load_settings(
    env_file: str | Path | None = None,
    environ: Mapping[str, str | None] | None = None,
) -> Settings:
    """Load and validate settings from dotenv and environment values."""

    return Settings.from_env(env_file=env_file, environ=environ)


def _load_raw_values(
    env_file: str | Path | None,
    environ: Mapping[str, str | None] | None,
) -> dict[str, str | None]:
    env_path = Path(env_file) if env_file is not None else Path(".env")
    raw: dict[str, str | None] = {}
    if env_path.exists():
        raw.update(dotenv_values(env_path))

    source = environ if environ is not None else os.environ
    for key, value in source.items():
        if value is not None:
            raw[key] = value
    return raw


def _parse_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_required_str(value: str | None, *, default: str, field_name: str) -> str:
    parsed = _parse_optional_str(value)
    result = parsed if parsed is not None else default
    if not result:
        raise ValueError(f"{field_name} must not be empty.")
    return result


def _parse_bool(value: str | None, *, default: bool, field_name: str) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    if normalized in truthy:
        return True
    if normalized in falsy:
        return False
    raise ValueError(f"{field_name} must be a boolean value.")


def _parse_int(value: str | None, *, default: int, field_name: str) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def _parse_float(value: str | None, *, default: float, field_name: str) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a float.") from exc


def _parse_enum(
    value: str | None,
    enum_type: type[EnumT],
    *,
    field_name: str,
    default: EnumT,
) -> EnumT:
    if value is None or value.strip() == "":
        return default
    try:
        return enum_type(value.strip())
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}.") from exc


def _validate_settings(settings: Settings) -> None:
    if settings.startup_candles_backfill < 0:
        raise ValueError("STARTUP_CANDLES_BACKFILL must be >= 0.")
    if settings.first_sell_qty_coin < 0:
        raise ValueError("FIRST_SELL_QTY_COIN must be >= 0.")
    if settings.base_order_pct_eq < 0:
        raise ValueError("BASE_ORDER_PCT_EQ must be >= 0.")
    if settings.equity_for_sizing_usdt < 0:
        raise ValueError("EQUITY_FOR_SIZING_USDT must be >= 0.")
    if settings.tp_percent < 0 or settings.callback_percent < 0 or settings.sub_sell_tp_percent < 0:
        raise ValueError("TP and callback percentages must be >= 0.")
    if settings.margin_call_limit < 0:
        raise ValueError("MARGIN_CALL_LIMIT must be >= 0.")
    if settings.max_orders_per_3min < 0 or settings.max_dca_per_bar < 0 or settings.max_subcover_per_bar < 0:
        raise ValueError("Risk counters must be >= 0.")
    if settings.api_max_retries < 0 or settings.api_backoff_base_seconds < 0:
        raise ValueError("API retry configuration must be >= 0.")
    if settings.telegram_max_messages_per_second < 0:
        raise ValueError("TELEGRAM_MAX_MESSAGES_PER_SECOND must be >= 0.")
    if settings.even_bar_anchor_mode == EvenBarAnchorMode.FIXED_TIMESTAMP:
        if settings.even_bar_fixed_timestamp is None:
            raise ValueError("EVEN_BAR_FIXED_TIMESTAMP is required when EVEN_BAR_ANCHOR_MODE=fixed_timestamp.")
        _validate_iso_datetime(settings.even_bar_fixed_timestamp, field_name="EVEN_BAR_FIXED_TIMESTAMP")


def _validate_iso_datetime(value: str, *, field_name: str) -> None:
    normalized = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO datetime string.") from exc
