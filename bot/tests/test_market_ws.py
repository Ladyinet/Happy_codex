"""Tests for the read-only BingX websocket market-data layer."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, EvenBarAnchorMode, Settings
from bot.data.candle_clock import CandleClock
from bot.data.market_stream import CandleUpdateBuffer
from bot.data.market_ws import (
    BingXMarketWebSocket,
    MarketWSError,
    build_kline_subscribe_message,
    parse_ws_message,
    websocket_interval_from_timeframe,
)
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.execution.dry_run_executor import DryRunExecutor
from bot.execution.order_manager import OrderManager
from bot.runner.orchestrator import DryRunOrchestrator
from bot.storage.models import BotState, InstrumentConstraints, SafeStopRecord
from bot.utils.rounding import OrderNormalizer


@dataclass
class InMemoryStorage:
    """Simple storage spy used for websocket-to-orchestrator integration tests."""

    states: list[BotState] = field(default_factory=list)
    orders: list[object] = field(default_factory=list)
    fills: list[object] = field(default_factory=list)
    events: list[object] = field(default_factory=list)
    safe_stops: list[SafeStopRecord] = field(default_factory=list)

    async def save_bot_state(self, state: BotState) -> None:
        self.states.append(state)

    async def save_order(self, order) -> None:
        self.orders.append(order)

    async def save_fill(self, fill) -> None:
        self.fills.append(fill)

    async def save_event(self, event) -> None:
        self.events.append(event)

    async def save_safe_stop_reason(self, record: SafeStopRecord) -> None:
        self.safe_stops.append(record)


class FakeWebSocket:
    """Minimal async websocket double with send and async-iteration support."""

    def __init__(self, messages: list[object]) -> None:
        self._messages = list(messages)
        self.sent_messages: list[str] = []

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> object:
        if not self._messages:
            raise StopAsyncIteration
        message = self._messages.pop(0)
        if isinstance(message, Exception):
            raise message
        return message


class FakeConnection:
    """Async context manager wrapper for the fake websocket."""

    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeConnector:
    """Connector that can fail first and then return fake websocket sessions."""

    def __init__(self, attempts: list[object]) -> None:
        self._attempts = list(attempts)
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        if not self._attempts:
            raise RuntimeError("No more fake connector attempts configured.")
        attempt = self._attempts.pop(0)
        if isinstance(attempt, Exception):
            raise attempt
        return FakeConnection(attempt)


async def _sleep_stub(_: float) -> None:
    return None


def _constraints() -> InstrumentConstraints:
    return InstrumentConstraints(
        symbol="BTC-USDT",
        tick_size=0.1,
        lot_step=0.001,
        min_qty=0.01,
        min_notional=10.0,
        price_precision=1,
        qty_precision=3,
    )


def _candle_payload(*, open_ms: int, close_ms: int, close: float) -> dict[str, object]:
    return {
        "dataType": "BTC-USDT@kline_1min",
        "data": {
            "E": close_ms,
            "K": {
                "t": open_ms,
                "T": close_ms,
                "o": str(close - 1),
                "h": str(close + 1),
                "l": str(close - 2),
                "c": str(close),
                "v": "10.0",
                "x": False,
            },
        },
    }


def _minute_ms(minute: int) -> int:
    dt = datetime(2026, 4, 10, 12, minute, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _candle(open_minute: int, close_minute: int, close: float):
    from bot.data.market_stream import Candle

    return Candle(
        open_time=datetime(2026, 4, 10, 12, open_minute, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 10, 12, close_minute, tzinfo=timezone.utc),
        open=close - 1,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1.0,
    )


def _orchestrator(*, storage: InMemoryStorage | None = None, clock: CandleClock | None = None) -> DryRunOrchestrator:
    storage = storage or InMemoryStorage()
    settings = Settings()
    runtime_state = BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m")
    return DryRunOrchestrator(
        symbol="BTC-USDT",
        timeframe="1m",
        runtime_state=runtime_state,
        storage=storage,
        candle_buffer=CandleUpdateBuffer(),
        candle_clock=clock
        or CandleClock(
            timeframe="1m",
            anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
            fixed_timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc),
        ),
        strategy_engine=StrategyEngine(),
        executor=DryRunExecutor(
            risk_manager=RiskManager(settings),
            order_manager=OrderManager(),
            position_manager=PositionManager(),
            order_normalizer=OrderNormalizer(settings.invalid_order_policy),
        ),
        constraints=_constraints(),
    )


@pytest.mark.asyncio
async def test_build_kline_subscribe_message_is_correct() -> None:
    message = build_kline_subscribe_message("BTC-USDT", "1m", request_id="abc")

    assert message == {
        "id": "abc",
        "dataType": "BTC-USDT@kline_1min",
    }


@pytest.mark.asyncio
async def test_timeframe_maps_to_official_websocket_interval() -> None:
    assert websocket_interval_from_timeframe("1m") == "1min"


@pytest.mark.asyncio
async def test_parse_ws_message_parses_candle_payload() -> None:
    parsed = parse_ws_message(
        json.dumps(
            _candle_payload(
                open_ms=_minute_ms(0),
                close_ms=_minute_ms(1),
                close=68458.1,
            )
        )
    )

    assert parsed.candle is not None
    assert parsed.candle.close == 68458.1
    assert parsed.candle.close_time == datetime(2026, 4, 10, 12, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_parse_ws_message_supports_gzip_bytes_payload() -> None:
    raw_payload = gzip.compress(
        json.dumps(
            _candle_payload(
                open_ms=_minute_ms(1),
                close_ms=_minute_ms(2),
                close=68459.1,
            )
        ).encode("utf-8")
    )

    parsed = parse_ws_message(raw_payload)

    assert parsed.candle is not None
    assert parsed.candle.close == 68459.1
    assert parsed.candle.close_time == datetime(2026, 4, 10, 12, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_parse_ws_message_supports_gzip_ping_and_returns_pong() -> None:
    raw_payload = gzip.compress(json.dumps({"ping": "12345", "time": "2026-04-08T10:00:00Z"}).encode("utf-8"))

    parsed = parse_ws_message(raw_payload)

    assert parsed.candle is None
    assert parsed.ignored is True
    assert parsed.reply_message == {"pong": "12345", "time": "2026-04-08T10:00:00Z"}


@pytest.mark.asyncio
async def test_parse_ws_message_supports_nested_dict_shape() -> None:
    payload = {
        "dataType": "BTC-USDT@kline_1min",
        "data": {
            "result": {
                "item": {
                    "t": str(_minute_ms(2)),
                    "T": str(_minute_ms(3)),
                    "o": "100.1",
                    "h": "101.1",
                    "l": "99.1",
                    "c": "100.9",
                    "v": "12.0",
                }
            }
        },
    }

    parsed = parse_ws_message(json.dumps(payload))

    assert parsed.candle is not None
    assert parsed.candle.close == 100.9
    assert parsed.candle.close_time == datetime(2026, 4, 10, 12, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_invalid_payload_is_skipped_by_stream_loop() -> None:
    websocket = FakeWebSocket(
        [
            json.dumps({"foo": "bar"}),
            json.dumps(_candle_payload(open_ms=_minute_ms(1), close_ms=_minute_ms(2), close=68459.1)),
        ]
    )
    connector = FakeConnector([websocket])
    statuses: list[str] = []
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub)

    candles = [
        candle
        async for candle in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            status_callback=statuses.append,
            max_candles=1,
        )
    ]

    assert len(candles) == 1
    assert candles[0].close == 68459.1
    assert any("candle_parse_failed:" in status for status in statuses)


@pytest.mark.asyncio
async def test_invalid_gzip_payload_is_skipped_by_stream_loop() -> None:
    websocket = FakeWebSocket(
        [
            b"not-a-valid-gzip-payload",
            gzip.compress(
                json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=68460.1)).encode(
                    "utf-8"
                )
            ),
        ]
    )
    connector = FakeConnector([websocket])
    statuses: list[str] = []
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub)

    candles = [
        candle
        async for candle in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            status_callback=statuses.append,
            max_candles=1,
        )
    ]

    assert len(candles) == 1
    assert candles[0].close == 68460.1
    assert any("candle_parse_failed:" in status for status in statuses)


@pytest.mark.asyncio
async def test_stream_candles_yields_internal_candle() -> None:
    websocket = FakeWebSocket(
        [json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=68460.1))]
    )
    connector = FakeConnector([websocket])
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub)

    candles = [
        candle
        async for candle in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            max_candles=1,
        )
    ]

    assert len(candles) == 1
    assert candles[0].close == 68460.1
    assert candles[0].close_time == datetime(2026, 4, 10, 12, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_candle_like_unsupported_shape_is_skipped_with_clear_reason() -> None:
    websocket = FakeWebSocket(
        [
            json.dumps({"dataType": "BTC-USDT@kline_1min", "data": {"unexpected": {"foo": "bar"}}}),
            json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=68460.1)),
        ]
    )
    connector = FakeConnector([websocket])
    statuses: list[str] = []
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub)

    candles = [
        candle
        async for candle in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            status_callback=statuses.append,
            max_candles=1,
        )
    ]

    assert len(candles) == 1
    assert any("candle_parse_failed:" in status for status in statuses)
    assert any("top_level_keys=" in status for status in statuses)


@pytest.mark.asyncio
async def test_reconnect_path_exists() -> None:
    second_socket = FakeWebSocket(
        [json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=68460.1))]
    )
    connector = FakeConnector([RuntimeError("first connection failed"), second_socket])
    statuses: list[str] = []
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub, reconnect_delay_seconds=0.0)

    candles = [
        candle
        async for candle in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            status_callback=statuses.append,
            reconnect_attempts=1,
            max_candles=1,
        )
    ]

    assert len(candles) == 1
    assert any(status.startswith("reconnecting after error:") for status in statuses)
    assert "connected" in statuses


@pytest.mark.asyncio
async def test_market_ws_layer_has_no_trading_dependency_requirement() -> None:
    connector = FakeConnector([FakeWebSocket([])])
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub)

    assert market_ws.ws_url.startswith("wss://")
    assert callable(market_ws.connector)


@pytest.mark.asyncio
async def test_mocked_ws_update_can_be_forwarded_to_orchestrator() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.warmup_from_candles([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])
    parsed = parse_ws_message(json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=102.0)))

    result = await orchestrator.process_market_update(parsed.candle)

    assert result.closed_bar_processed is True
    assert len(result.execution_results) == 1
    assert len(storage.orders) == 1
    assert len(storage.fills) == 1


@pytest.mark.asyncio
async def test_duplicate_or_old_ws_update_does_not_repeat_execution() -> None:
    storage = InMemoryStorage()
    orchestrator = _orchestrator(storage=storage)

    await orchestrator.warmup_from_candles([_candle(0, 1, 100.0), _candle(1, 2, 101.0)])
    parsed = parse_ws_message(json.dumps(_candle_payload(open_ms=_minute_ms(2), close_ms=_minute_ms(3), close=102.0)))
    await orchestrator.process_market_update(parsed.candle)
    initial_orders = len(storage.orders)

    duplicate_result = await orchestrator.process_market_update(parsed.candle)
    old_result = await orchestrator.process_market_update(_candle(1, 2, 101.0))

    assert len(storage.orders) == initial_orders
    assert duplicate_result.closed_bar_processed is False
    assert old_result.closed_bar_processed is False


@pytest.mark.asyncio
async def test_reconnect_limit_raises_market_ws_error() -> None:
    connector = FakeConnector([RuntimeError("boom"), RuntimeError("boom-again")])
    market_ws = BingXMarketWebSocket(connector=connector, sleep=_sleep_stub, reconnect_delay_seconds=0.0)

    with pytest.raises(MarketWSError):
        async for _ in market_ws.stream_candles(
            symbol="BTC-USDT",
            timeframe="1m",
            reconnect_attempts=1,
            max_candles=1,
        ):
            pass
