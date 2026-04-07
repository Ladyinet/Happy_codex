"""Debug helper for inspecting the raw BingX metadata payload for one symbol."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import aiohttp


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.config import load_settings
from bot.exchange.bingx_client import (
    CONTRACTS_ENDPOINT,
    DEFAULT_BINGX_BASE_URL,
    DEFAULT_BINGX_TESTNET_BASE_URL,
)


async def _run() -> int:
    settings = load_settings(PROJECT_ROOT / ".env")
    base_url = DEFAULT_BINGX_TESTNET_BASE_URL if settings.bingx_testnet else DEFAULT_BINGX_BASE_URL
    url = f"{base_url.rstrip('/')}{CONTRACTS_ENDPOINT}"
    params = {"symbol": settings.symbol}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15.0)) as session:
            async with session.get(url, params=params) as response:
                text_body = await response.text()
                if response.status >= 400:
                    print(f"HTTP error: {response.status}", file=sys.stderr)
                    print(text_body, file=sys.stderr)
                    return 1
                try:
                    payload = json.loads(text_body)
                except json.JSONDecodeError as exc:
                    print(f"Response is not valid JSON: {exc}", file=sys.stderr)
                    print(text_body, file=sys.stderr)
                    return 1
    except Exception as exc:
        print(f"Metadata debug request failed: {exc}", file=sys.stderr)
        return 1

    print(f"request_url: {url}")
    print(f"symbol: {settings.symbol}")
    print(f"top_level_keys: {_top_level_keys(payload)}")

    data = payload.get("data")
    print(f"data_type: {type(data).__name__}")
    print(f"data_structure: {_describe_structure(data)}")

    if isinstance(data, list):
        print("data_first_item:")
        print(_pretty_json(data[0] if data else None))
    elif isinstance(data, dict):
        for key in ("contracts", "symbols", "result", "items"):
            if key in data:
                print(f"data_{key}:")
                print(_pretty_json(data[key]))

    matched_symbol = _find_symbol_payload(data, settings.symbol)
    if matched_symbol is not None:
        print(f"matched_symbol_payload[{settings.symbol!r}]:")
        print(_pretty_json(matched_symbol))
    else:
        print(f"matched_symbol_payload[{settings.symbol!r}]: not found")

    return 0


def _top_level_keys(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys())
    return []


def _describe_structure(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "list(empty)"
        first = value[0]
        if isinstance(first, dict):
            return f"list[dict] len={len(value)} keys={sorted(first.keys())}"
        return f"list[{type(first).__name__}] len={len(value)}"
    if isinstance(value, dict):
        return f"dict keys={sorted(value.keys())}"
    return type(value).__name__


def _find_symbol_payload(data: Any, symbol: str) -> dict[str, Any] | None:
    if isinstance(data, dict):
        if data.get("symbol") == symbol:
            return data

        for key in ("contracts", "symbols", "result", "items"):
            nested = data.get(key)
            match = _find_symbol_payload(nested, symbol)
            if match is not None:
                return match

        for value in data.values():
            match = _find_symbol_payload(value, symbol)
            if match is not None:
                return match
        return None

    if isinstance(data, list):
        for item in data:
            match = _find_symbol_payload(item, symbol)
            if match is not None:
                return match
        return None

    return None


def _pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
