"""Thin read-only BingX REST client for market metadata and historical candles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp

from bot.exchange.metadata import BingXMetadataError, metadata_to_instrument_constraints
from bot.storage.models import InstrumentConstraints
from bot.utils.time_utils import timeframe_to_seconds


DEFAULT_BINGX_BASE_URL = "https://open-api.bingx.com"
DEFAULT_BINGX_TESTNET_BASE_URL = "https://open-api-vst.bingx.com"
CONTRACTS_ENDPOINT = "/openApi/swap/v2/quote/contracts"
KLINES_ENDPOINT = "/openApi/swap/v3/quote/klines"


class BingXClientError(RuntimeError):
    """Raised when a read-only BingX REST request fails."""


class BingXPayloadError(ValueError):
    """Raised when a BingX response payload is structurally unsupported."""


@dataclass(slots=True)
class BingXHistoricalCandle:
    """Typed raw historical candle returned by the BingX REST client."""

    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class HTTPSessionProtocol(Protocol):
    """Minimal protocol used by the read-only client for testability."""

    def get(self, url: str, *, params: dict[str, Any] | None = None):  # pragma: no cover
        """Return an async context manager for one GET request."""

    async def close(self) -> None:
        """Close the underlying HTTP session."""


class BingXClient:
    """Thin read-only client for public BingX market-data endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        testnet: bool = False,
        timeout_seconds: float = 10.0,
        session: HTTPSessionProtocol | None = None,
    ) -> None:
        self.base_url = (base_url or (DEFAULT_BINGX_TESTNET_BASE_URL if testnet else DEFAULT_BINGX_BASE_URL)).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "BingXClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the owned HTTP session, if one was created by the client."""

        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch_metadata(self, symbol: str) -> dict[str, Any]:
        """Fetch raw instrument metadata for one symbol."""

        payload = await self._get_json(CONTRACTS_ENDPOINT, params={"symbol": symbol})
        data = _extract_response_data(payload)
        return _extract_symbol_metadata(data, symbol)

    async def fetch_instrument_constraints(self, symbol: str) -> InstrumentConstraints:
        """Fetch and convert exchange metadata into internal constraints."""

        metadata = await self.fetch_metadata(symbol)
        try:
            return metadata_to_instrument_constraints(metadata)
        except BingXMetadataError as exc:
            raise BingXPayloadError(str(exc)) from exc

    async def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int) -> list[BingXHistoricalCandle]:
        """Fetch historical public candles for startup backfill."""

        payload = await self._get_json(
            KLINES_ENDPOINT,
            params={"symbol": symbol, "interval": timeframe, "limit": limit},
        )
        data = _extract_response_data(payload)
        rows = _extract_candle_rows(data)
        return [_parse_candle_row(row=row, symbol=symbol, timeframe=timeframe) for row in rows]

    async def _ensure_session(self) -> HTTPSessionProtocol:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self.base_url}{path}"
        async with session.get(url, params=params) as response:
            if response.status >= 400:
                body = await response.text()
                raise BingXClientError(f"GET {path} failed with HTTP {response.status}: {body}")
            try:
                payload = await response.json()
            except Exception as exc:  # pragma: no cover
                raise BingXClientError(f"GET {path} returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise BingXPayloadError("BingX response payload must be a JSON object.")
        return payload


def _extract_response_data(payload: dict[str, Any]) -> Any:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        raise BingXClientError(f"BingX returned an error code: {code}")
    if "data" not in payload:
        raise BingXPayloadError("BingX response payload is missing 'data'.")
    return payload["data"]


def _extract_symbol_metadata(data: Any, symbol: str) -> dict[str, Any]:
    if isinstance(data, dict):
        if data.get("symbol") == symbol:
            return data
        for key in ("symbols", "contracts"):
            nested = data.get(key)
            if isinstance(nested, list):
                match = _find_symbol_entry(nested, symbol)
                if match is not None:
                    return match
    if isinstance(data, list):
        match = _find_symbol_entry(data, symbol)
        if match is not None:
            return match
    raise BingXPayloadError(f"Metadata for symbol '{symbol}' was not found in the BingX response.")


def _find_symbol_entry(rows: list[Any], symbol: str) -> dict[str, Any] | None:
    for row in rows:
        if isinstance(row, dict) and row.get("symbol") == symbol:
            return row
    return None


def _extract_candle_rows(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("candles", "klines", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return rows
    raise BingXPayloadError("Candle payload is missing a supported list of rows.")


def _parse_candle_row(*, row: Any, symbol: str, timeframe: str) -> BingXHistoricalCandle:
    if isinstance(row, dict):
        return _parse_candle_dict(row=row, symbol=symbol, timeframe=timeframe)
    if isinstance(row, list):
        return _parse_candle_list(row=row, symbol=symbol, timeframe=timeframe)
    raise BingXPayloadError("Each candle row must be a dict or a list.")


def _parse_candle_dict(*, row: dict[str, Any], symbol: str, timeframe: str) -> BingXHistoricalCandle:
    open_time_ms = _require_int(row, ("openTime", "open_time", "time"), "openTime")
    close_time_ms = _optional_int(row, ("closeTime", "close_time")) or _derive_close_time_ms(
        open_time_ms=open_time_ms,
        timeframe=timeframe,
    )
    return BingXHistoricalCandle(
        symbol=symbol,
        interval=timeframe,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open=_require_float(row, ("open",), "open"),
        high=_require_float(row, ("high",), "high"),
        low=_require_float(row, ("low",), "low"),
        close=_require_float(row, ("close",), "close"),
        volume=_require_float(row, ("volume",), "volume"),
    )


def _parse_candle_list(*, row: list[Any], symbol: str, timeframe: str) -> BingXHistoricalCandle:
    if len(row) < 6:
        raise BingXPayloadError("Candle list rows must contain at least 6 elements.")

    open_time_ms = _to_int(row[0], field_name="candle[0]")
    close_time_ms = _to_int(row[6], field_name="candle[6]") if len(row) >= 7 else _derive_close_time_ms(
        open_time_ms=open_time_ms,
        timeframe=timeframe,
    )
    return BingXHistoricalCandle(
        symbol=symbol,
        interval=timeframe,
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open=_to_float(row[1], field_name="candle[1]"),
        high=_to_float(row[2], field_name="candle[2]"),
        low=_to_float(row[3], field_name="candle[3]"),
        close=_to_float(row[4], field_name="candle[4]"),
        volume=_to_float(row[5], field_name="candle[5]"),
    )


def _derive_close_time_ms(*, open_time_ms: int, timeframe: str) -> int:
    return open_time_ms + timeframe_to_seconds(timeframe) * 1000


def _require_int(payload: dict[str, Any], keys: tuple[str, ...], field_name: str) -> int:
    value = _optional_int(payload, keys)
    if value is None:
        raise BingXPayloadError(f"Missing required candle field '{field_name}'.")
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
    raise BingXPayloadError(f"Missing required candle field '{field_name}'.")


def _to_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BingXPayloadError(f"Field '{field_name}' must be an integer-compatible value.") from exc


def _to_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BingXPayloadError(f"Field '{field_name}' must be a float-compatible value.") from exc
