"""Tests for the read-only BingX client and metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bot.exchange.bingx_client import BingXClient, BingXClientError, BingXPayloadError
from bot.exchange.metadata import BingXMetadataError, metadata_to_instrument_constraints


@dataclass
class FakeResponse:
    """Async context-manager response stub used by client tests."""

    payload: object
    status: int = 200
    text_body: str = ""

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self):
        return self.payload

    async def text(self) -> str:
        return self.text_body


class FakeSession:
    """Simple fake aiohttp-like session with queued responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict | None]] = []

    def get(self, url: str, *, params: dict | None = None) -> FakeResponse:
        self.requests.append((url, params))
        return self.responses.pop(0)

    async def close(self) -> None:
        return None


def _metadata_payload() -> dict:
    return {
        "code": 0,
        "data": [
            {
                "symbol": "BTC-USDT",
                "pricePrecision": 1,
                "quantityPrecision": 3,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.01"},
                    {"filterType": "MIN_NOTIONAL", "notional": "10"},
                ],
            }
        ],
    }


def _candles_payload() -> dict:
    return {
        "code": 0,
        "data": [
            [1712731200000, "100.0", "101.0", "99.5", "100.5", "12.0", 1712731260000],
            [1712731260000, "100.5", "102.0", "100.0", "101.5", "14.0", 1712731320000],
        ],
    }


def test_metadata_is_converted_to_instrument_constraints() -> None:
    constraints = metadata_to_instrument_constraints(_metadata_payload()["data"][0])

    assert constraints.symbol == "BTC-USDT"
    assert constraints.tick_size == 0.1
    assert constraints.lot_step == 0.001
    assert constraints.min_qty == 0.01
    assert constraints.min_notional == 10.0
    assert constraints.price_precision == 1
    assert constraints.qty_precision == 3


def test_invalid_metadata_payload_raises_clear_error() -> None:
    with pytest.raises(BingXMetadataError, match="Missing required metadata field"):
        metadata_to_instrument_constraints({"symbol": "BTC-USDT"})


@pytest.mark.asyncio
async def test_fetch_instrument_constraints_uses_read_only_metadata_endpoint() -> None:
    session = FakeSession([FakeResponse(_metadata_payload())])
    client = BingXClient(session=session, base_url="https://open-api.bingx.test")

    constraints = await client.fetch_instrument_constraints("BTC-USDT")

    assert constraints.symbol == "BTC-USDT"
    assert session.requests[0][0].endswith("/openApi/swap/v2/quote/contracts")
    assert session.requests[0][1] == {"symbol": "BTC-USDT"}


@pytest.mark.asyncio
async def test_fetch_historical_candles_parses_rows() -> None:
    session = FakeSession([FakeResponse(_candles_payload())])
    client = BingXClient(session=session, base_url="https://open-api.bingx.test")

    candles = await client.fetch_historical_candles("BTC-USDT", "1m", 2)

    assert len(candles) == 2
    assert candles[0].open_time_ms == 1712731200000
    assert candles[0].close == 100.5
    assert candles[1].close_time_ms == 1712731320000


@pytest.mark.asyncio
async def test_invalid_candle_payload_raises_clear_error() -> None:
    session = FakeSession([FakeResponse({"code": 0, "data": [{"open": "100.0"}]})])
    client = BingXClient(session=session)

    with pytest.raises(BingXPayloadError, match="Missing required candle field"):
        await client.fetch_historical_candles("BTC-USDT", "1m", 1)


@pytest.mark.asyncio
async def test_http_error_raises_client_error() -> None:
    session = FakeSession([FakeResponse({"error": "boom"}, status=500, text_body="boom")])
    client = BingXClient(session=session)

    with pytest.raises(BingXClientError, match="HTTP 500"):
        await client.fetch_metadata("BTC-USDT")
