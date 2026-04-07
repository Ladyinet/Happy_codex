"""Helpers for parsing BingX instrument metadata into internal constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.storage.models import InstrumentConstraints


class BingXMetadataError(ValueError):
    """Raised when exchange metadata is incomplete or structurally unsupported."""


@dataclass(slots=True)
class BingXInstrumentMetadata:
    """Thin typed wrapper around one raw BingX instrument metadata payload."""

    raw: dict[str, Any]


def metadata_to_instrument_constraints(metadata: dict[str, Any] | BingXInstrumentMetadata) -> InstrumentConstraints:
    """Convert one raw BingX metadata payload into internal normalization constraints."""

    raw = metadata.raw if isinstance(metadata, BingXInstrumentMetadata) else metadata
    symbol = _require_str(raw, ("symbol",))
    return InstrumentConstraints(
        symbol=symbol,
        tick_size=extract_tick_size(raw),
        lot_step=extract_lot_step(raw),
        min_qty=extract_min_qty(raw),
        min_notional=extract_min_notional(raw),
        price_precision=extract_price_precision(raw),
        qty_precision=extract_qty_precision(raw),
    )


def extract_tick_size(raw: dict[str, Any]) -> float:
    """Extract price tick size from one BingX symbol payload."""

    return _require_float(raw, direct_keys=("tickSize", "priceTick"), filter_type="PRICE_FILTER", filter_keys=("tickSize",))


def extract_lot_step(raw: dict[str, Any]) -> float:
    """Extract quantity step size from one BingX symbol payload."""

    return _require_float(raw, direct_keys=("stepSize", "lotStep", "quantityStep"), filter_type="LOT_SIZE", filter_keys=("stepSize",))


def extract_min_qty(raw: dict[str, Any]) -> float:
    """Extract minimum order quantity from one BingX symbol payload."""

    return _require_float(raw, direct_keys=("minQty", "quantityMin"), filter_type="LOT_SIZE", filter_keys=("minQty",))


def extract_min_notional(raw: dict[str, Any]) -> float:
    """Extract minimum notional from one BingX symbol payload."""

    return _require_float(
        raw,
        direct_keys=("minNotional", "notional", "minOrderValue"),
        filter_type="MIN_NOTIONAL",
        filter_keys=("minNotional", "notional"),
    )


def extract_price_precision(raw: dict[str, Any]) -> int:
    """Extract price precision from one BingX symbol payload."""

    return _require_int(raw, direct_keys=("pricePrecision",), fallback_value=extract_tick_size(raw))


def extract_qty_precision(raw: dict[str, Any]) -> int:
    """Extract quantity precision from one BingX symbol payload."""

    return _require_int(raw, direct_keys=("quantityPrecision", "qtyPrecision"), fallback_value=extract_lot_step(raw))


def _require_float(
    raw: dict[str, Any],
    *,
    direct_keys: tuple[str, ...],
    filter_type: str,
    filter_keys: tuple[str, ...],
) -> float:
    for key in direct_keys:
        if key in raw and raw[key] is not None:
            return _to_float(raw[key], field_name=key)

    filter_payload = _find_filter(raw, filter_type)
    if filter_payload is not None:
        for key in filter_keys:
            if key in filter_payload and filter_payload[key] is not None:
                return _to_float(filter_payload[key], field_name=f"{filter_type}.{key}")

    key_list = ", ".join((*direct_keys, *(f"{filter_type}.{key}" for key in filter_keys)))
    raise BingXMetadataError(f"Missing required metadata field: {key_list}")


def _require_int(
    raw: dict[str, Any],
    *,
    direct_keys: tuple[str, ...],
    fallback_value: float,
) -> int:
    for key in direct_keys:
        if key in raw and raw[key] is not None:
            return _to_int(raw[key], field_name=key)
    return _precision_from_step(fallback_value)


def _find_filter(raw: dict[str, Any], filter_type: str) -> dict[str, Any] | None:
    filters = raw.get("filters")
    if not isinstance(filters, list):
        return None

    for item in filters:
        if not isinstance(item, dict):
            continue
        if item.get("filterType") == filter_type:
            return item
    return None


def _require_str(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise BingXMetadataError(f"Missing required metadata field: {', '.join(keys)}")


def _to_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BingXMetadataError(f"Field '{field_name}' must be a float-compatible value.") from exc


def _to_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BingXMetadataError(f"Field '{field_name}' must be an integer-compatible value.") from exc


def _precision_from_step(step: float) -> int:
    step_text = f"{step:.16f}".rstrip("0").rstrip(".")
    if "." not in step_text:
        return 0
    return len(step_text.split(".", maxsplit=1)[1])
