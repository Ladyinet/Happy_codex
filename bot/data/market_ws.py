"""Read-only BingX websocket transport for public candle updates."""

from __future__ import annotations

import asyncio
import gzip
import inspect
import json
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

import websockets

from bot.data.market_stream import Candle
from bot.utils.time_utils import ensure_utc, timeframe_to_seconds


DEFAULT_BINGX_WS_URL = "wss://open-api-ws.bingx.com/market"

INTERNAL_TO_WS_TIMEFRAME: dict[str, str] = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1hour",
    "4h": "4hour",
    "1d": "1day",
}
WS_TO_INTERNAL_TIMEFRAME: dict[str, str] = {value: key for key, value in INTERNAL_TO_WS_TIMEFRAME.items()}


class MarketWSError(RuntimeError):
    """Raised when the websocket feed cannot continue safely."""


class MarketWSPayloadError(ValueError):
    """Raised when a websocket payload cannot be parsed into a candle."""


@dataclass(slots=True)
class ParsedWSMessage:
    """Structured result of parsing one websocket message."""

    candle: Candle | None = None
    ignored: bool = False
    reason: str | None = None
    reply_message: dict[str, Any] | None = None


class WebSocketProtocol(Protocol):
    """Minimal websocket protocol used for testable streaming."""

    async def send(self, message: str) -> None:
        """Send one text message to the websocket peer."""

    def __aiter__(self):
        """Iterate over incoming websocket messages."""


StatusCallback = Callable[[str], Awaitable[None] | None]


def build_ws_url(*, base_url: str | None = None, testnet: bool = False) -> str:
    """Return the public BingX websocket URL for read-only market data."""

    if base_url is not None:
        return base_url
    return DEFAULT_BINGX_WS_URL


def build_kline_subscribe_message(symbol: str, timeframe: str, *, request_id: str | None = None) -> dict[str, str]:
    """Build a public kline subscription request.

    v1 assumption:
    BingX public market subscriptions use the pattern:
    ``{"id": "...", "dataType": "BTC-USDT@kline_1min"}``
    """

    ws_interval = websocket_interval_from_timeframe(timeframe)
    return {
        "id": request_id or f"sub:{symbol}:{timeframe}",
        "dataType": f"{symbol}@kline_{ws_interval}",
    }


def parse_ws_message(raw_message: str | bytes) -> ParsedWSMessage:
    """Parse one raw websocket message into the internal candle model.

    Supported v1 payload shapes:
    - ``{"ping": "...", "time": "..."}`` -> produces a pong reply in the same format
    - ack/status messages -> safely ignored
    - kline payloads with ``dataType="BTC-USDT@kline_1min"`` and either:
      - ``data`` as a candle dict
      - ``data`` as a list where the last item is a candle dict/list
      - ``data`` containing nested ``k`` / ``K`` candle dict
    """

    payload = _decode_json_payload(raw_message)

    if "ping" in payload:
        reply_message = {"pong": payload["ping"]}
        if "time" in payload:
            reply_message["time"] = payload["time"]
        return ParsedWSMessage(
            ignored=True,
            reason="ping",
            reply_message=reply_message,
        )

    if _is_ack_or_status_message(payload):
        return ParsedWSMessage(ignored=True, reason="ack_or_status")

    channel = payload.get("dataType")
    if not isinstance(channel, str):
        raise MarketWSPayloadError("Websocket payload is missing string field 'dataType'.")
    if "@kline_" not in channel:
        return ParsedWSMessage(ignored=True, reason="unsupported_channel")

    timeframe = _extract_timeframe_from_channel(channel)
    candle = _parse_candle_payload(payload.get("data"), timeframe=timeframe)
    return ParsedWSMessage(candle=candle)


class BingXMarketWebSocket:
    """Thin read-only websocket client for public BingX kline updates."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        testnet: bool = False,
        connector: Callable[[str], Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        reconnect_delay_seconds: float = 2.0,
    ) -> None:
        self.ws_url = build_ws_url(base_url=base_url, testnet=testnet)
        self.connector = connector or websockets.connect
        self.sleep = sleep
        self.reconnect_delay_seconds = reconnect_delay_seconds

    async def stream_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        status_callback: StatusCallback | None = None,
        reconnect_attempts: int | None = None,
        max_candles: int | None = None,
        debug: bool = False,
        debug_message_limit: int = 10,
    ):
        """Yield normalized public candle updates with simple reconnect support."""

        delivered = 0
        failures = 0

        while True:
            await _emit_status(status_callback, f"connecting:{self.ws_url}")
            try:
                async with self.connector(self.ws_url) as websocket:
                    failures = 0
                    await _emit_status(status_callback, "connected")
                    subscribe_message = build_kline_subscribe_message(symbol, timeframe)
                    await websocket.send(json.dumps(subscribe_message))
                    if debug:
                        await _emit_status(status_callback, f"subscribe sent: {json.dumps(subscribe_message)}")
                    debug_messages_seen = 0

                    async for raw_message in websocket:
                        if debug and debug_messages_seen < debug_message_limit:
                            debug_messages_seen += 1
                            await _emit_status(status_callback, _format_debug_message(raw_message, debug_messages_seen))
                        try:
                            parsed = parse_ws_message(raw_message)
                        except MarketWSPayloadError as exc:
                            await _emit_status(status_callback, f"skipping invalid payload: {exc}")
                            continue

                        if parsed.reply_message is not None:
                            await websocket.send(json.dumps(parsed.reply_message))
                        if parsed.candle is None:
                            continue

                        yield parsed.candle
                        delivered += 1
                        if max_candles is not None and delivered >= max_candles:
                            return

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                await _emit_status(status_callback, f"reconnecting after error: {exc}")
                if reconnect_attempts is not None and failures > reconnect_attempts:
                    raise MarketWSError(f"Websocket reconnect limit reached for {symbol} {timeframe}.") from exc
                await self.sleep(self.reconnect_delay_seconds)


async def _emit_status(callback: StatusCallback | None, message: str) -> None:
    """Emit one optional status callback that may be sync or async."""

    if callback is None:
        return
    result = callback(message)
    if inspect.isawaitable(result):
        await result


def _decode_json_payload(raw_message: str | bytes) -> dict[str, Any]:
    if isinstance(raw_message, bytes):
        decoded = _decode_bytes_payload(raw_message)
    else:
        decoded = raw_message

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise MarketWSPayloadError("Websocket message is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise MarketWSPayloadError("Websocket JSON payload must be an object.")
    return payload


def _decode_bytes_payload(raw_message: bytes) -> str:
    decompressors = (
        lambda value: gzip.decompress(value),
        lambda value: zlib.decompress(value, zlib.MAX_WBITS | 16),
        lambda value: zlib.decompress(value),
    )
    for decompressor in decompressors:
        try:
            return decompressor(raw_message).decode("utf-8")
        except Exception:
            continue

    try:
        return raw_message.decode("utf-8")
    except UnicodeDecodeError:
        pass

    raise MarketWSPayloadError("Unable to decode websocket binary payload.")


def _is_ack_or_status_message(payload: dict[str, Any]) -> bool:
    if "success" in payload:
        return True
    if "code" in payload and "data" not in payload and "dataType" not in payload:
        return True
    if payload.get("reqType") in {"sub", "unsub"}:
        return True
    return False


def _format_debug_message(raw_message: str | bytes, sequence: int) -> str:
    """Return a short human-readable debug summary for one raw websocket message."""

    try:
        payload = _decode_json_payload(raw_message)
    except MarketWSPayloadError as exc:
        return f"ws_debug[{sequence}] invalid payload: {exc}"

    keys = sorted(str(key) for key in payload.keys())
    data_type = payload.get("dataType")

    if _is_subscribe_ack(payload):
        return (
            f"ws_debug[{sequence}] ack "
            f"id={payload.get('id')} code={payload.get('code')} msg={payload.get('msg', '')!r}"
        )

    if "ping" in payload:
        return f"ws_debug[{sequence}] ping ping={payload.get('ping')!r} time={payload.get('time')!r}"

    if isinstance(data_type, str) and "@kline_" in data_type:
        return f"ws_debug[{sequence}] candle_update dataType={data_type}"

    return f"ws_debug[{sequence}] unknown keys={keys} dataType={data_type!r}"


def _is_subscribe_ack(payload: dict[str, Any]) -> bool:
    return "id" in payload and payload.get("code") in (0, "0")


def _extract_timeframe_from_channel(channel: str) -> str:
    _, _, timeframe = channel.partition("@kline_")
    if not timeframe:
        raise MarketWSPayloadError(f"Unable to extract timeframe from channel '{channel}'.")
    return WS_TO_INTERNAL_TIMEFRAME.get(timeframe, timeframe)


def websocket_interval_from_timeframe(timeframe: str) -> str:
    """Map internal timeframe notation to the public BingX websocket interval format."""

    try:
        return INTERNAL_TO_WS_TIMEFRAME[timeframe]
    except KeyError as exc:
        allowed = ", ".join(sorted(INTERNAL_TO_WS_TIMEFRAME))
        raise MarketWSPayloadError(
            f"Unsupported websocket timeframe '{timeframe}'. Allowed values: {allowed}."
        ) from exc


def _parse_candle_payload(data: Any, *, timeframe: str) -> Candle:
    candidate = data
    if isinstance(candidate, dict) and isinstance(candidate.get("K"), dict):
        candidate = candidate["K"]
    elif isinstance(candidate, dict) and isinstance(candidate.get("k"), dict):
        candidate = candidate["k"]
    elif isinstance(candidate, list):
        if not candidate:
            raise MarketWSPayloadError("Kline payload list must not be empty.")
        candidate = candidate[-1]

    if isinstance(candidate, dict):
        return _parse_candle_dict(candidate, timeframe=timeframe)
    if isinstance(candidate, list):
        return _parse_candle_list(candidate, timeframe=timeframe)
    raise MarketWSPayloadError("Unsupported websocket candle payload structure.")


def _parse_candle_dict(payload: dict[str, Any], *, timeframe: str) -> Candle:
    open_time_ms = _require_int(payload, ("t", "openTime", "open_time", "time"), "openTime")
    close_time_ms = _optional_int(payload, ("T", "closeTime", "close_time"))
    if close_time_ms is None:
        close_time_ms = open_time_ms + timeframe_to_seconds(timeframe) * 1000

    return Candle(
        open_time=_ms_to_utc(open_time_ms),
        close_time=_ms_to_utc(close_time_ms),
        open=_require_float(payload, ("o", "open"), "open"),
        high=_require_float(payload, ("h", "high"), "high"),
        low=_require_float(payload, ("l", "low"), "low"),
        close=_require_float(payload, ("c", "close"), "close"),
        volume=_require_float(payload, ("v", "volume"), "volume"),
        is_closed=_optional_bool(payload, ("x", "isClosed"), default=False),
    )


def _parse_candle_list(payload: list[Any], *, timeframe: str) -> Candle:
    if len(payload) < 6:
        raise MarketWSPayloadError("Websocket candle list payload must contain at least 6 elements.")

    open_time_ms = _to_int(payload[0], field_name="candle[0]")
    close_time_ms = (
        _to_int(payload[6], field_name="candle[6]")
        if len(payload) >= 7 and payload[6] is not None
        else open_time_ms + timeframe_to_seconds(timeframe) * 1000
    )
    is_closed = _to_bool(payload[7], field_name="candle[7]") if len(payload) >= 8 else False
    return Candle(
        open_time=_ms_to_utc(open_time_ms),
        close_time=_ms_to_utc(close_time_ms),
        open=_to_float(payload[1], field_name="candle[1]"),
        high=_to_float(payload[2], field_name="candle[2]"),
        low=_to_float(payload[3], field_name="candle[3]"),
        close=_to_float(payload[4], field_name="candle[4]"),
        volume=_to_float(payload[5], field_name="candle[5]"),
        is_closed=is_closed,
    )


def _ms_to_utc(value: int) -> datetime:
    return ensure_utc(datetime.fromtimestamp(value / 1000, tz=timezone.utc))


def _require_int(payload: dict[str, Any], keys: tuple[str, ...], field_name: str) -> int:
    value = _optional_int(payload, keys)
    if value is None:
        raise MarketWSPayloadError(f"Missing required websocket candle field '{field_name}'.")
    return value


def _optional_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _to_int(payload[key], field_name=key)
    return None


def _require_float(payload: dict[str, Any], keys: tuple[str, ...], field_name: str) -> float:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _to_float(payload[key], field_name=key)
    raise MarketWSPayloadError(f"Missing required websocket candle field '{field_name}'.")


def _optional_bool(payload: dict[str, Any], keys: tuple[str, ...], *, default: bool) -> bool:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _to_bool(payload[key], field_name=key)
    return default


def _to_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MarketWSPayloadError(f"Field '{field_name}' must be integer-compatible.") from exc


def _to_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise MarketWSPayloadError(f"Field '{field_name}' must be float-compatible.") from exc


def _to_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise MarketWSPayloadError(f"Field '{field_name}' must be bool-compatible.")
