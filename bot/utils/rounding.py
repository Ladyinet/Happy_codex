"""Shared order normalization for dry_run and future live mode."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from bot.config import InvalidOrderPolicy
from bot.storage.models import InstrumentConstraints, NormalizedOrder


def normalize_price_to_tick(price: float, tick_size: float, price_precision: int) -> float:
    """Round price down to the nearest valid tick without increasing nominal risk."""

    if price <= 0:
        raise ValueError("price must be > 0.")
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0.")
    return _quantize_down(value=price, step=tick_size, precision=price_precision)


def normalize_qty_to_step(qty: float, lot_step: float, qty_precision: int) -> float:
    """Round quantity down to the nearest valid lot step without increasing exposure."""

    if qty < 0:
        raise ValueError("qty must be >= 0.")
    if lot_step <= 0:
        raise ValueError("lot_step must be > 0.")
    return _quantize_down(value=qty, step=lot_step, precision=qty_precision)


def compute_notional(price: float | None, qty: float) -> float | None:
    """Return notional when a reference price is available."""

    if price is None:
        return None
    return price * qty


def check_minimum_requirements(
    *,
    price: float | None,
    qty: float,
    constraints: InstrumentConstraints,
) -> str | None:
    """Return an invalidation reason if minimum exchange requirements are not met."""

    if qty <= 0:
        return "normalized quantity is zero after safe rounding"
    if qty < constraints.min_qty:
        return "normalized quantity is below min_qty"

    notional = compute_notional(price, qty)
    if notional is not None and notional < constraints.min_notional:
        return "normalized order is below min_notional"
    return None


class OrderNormalizer:
    """Normalize order price and quantity through one shared v1 path."""

    def __init__(self, invalid_order_policy: InvalidOrderPolicy) -> None:
        self.invalid_order_policy = invalid_order_policy

    def normalize_order(
        self,
        symbol: str,
        price: float | None,
        qty: float,
        constraints: InstrumentConstraints,
    ) -> NormalizedOrder:
        """Normalize one order without increasing exposure.

        v1 rule:
        - quantity is never rounded up to satisfy min_qty or min_notional
        - invalid orders remain invalid after safe normalization
        """

        if symbol != constraints.symbol:
            return self._invalid_result(symbol=symbol, price=price, qty=qty, reason="symbol does not match constraints")
        if qty < 0:
            return self._invalid_result(symbol=symbol, price=price, qty=qty, reason="quantity must be >= 0")
        if price is not None and price <= 0:
            return self._invalid_result(symbol=symbol, price=price, qty=qty, reason="price must be > 0")

        normalized_price = None
        if price is not None:
            normalized_price = normalize_price_to_tick(
                price=price,
                tick_size=constraints.tick_size,
                price_precision=constraints.price_precision,
            )

        normalized_qty = normalize_qty_to_step(
            qty=qty,
            lot_step=constraints.lot_step,
            qty_precision=constraints.qty_precision,
        )

        invalid_reason = check_minimum_requirements(
            price=normalized_price,
            qty=normalized_qty,
            constraints=constraints,
        )
        if invalid_reason is not None:
            return self._invalid_result(
                symbol=symbol,
                price=normalized_price,
                qty=normalized_qty,
                reason=invalid_reason,
            )

        return NormalizedOrder(
            symbol=symbol,
            price=normalized_price,
            qty=normalized_qty,
            is_valid=True,
            reason=None,
        )

    def _invalid_result(
        self,
        *,
        symbol: str,
        price: float | None,
        qty: float,
        reason: str,
    ) -> NormalizedOrder:
        """Build a policy-aware invalid normalization result."""

        return NormalizedOrder(
            symbol=symbol,
            price=price,
            qty=qty,
            is_valid=False,
            reason=f"{self.invalid_order_policy.value}: {reason}",
        )


def _quantize_down(*, value: float, step: float, precision: int) -> float:
    """Round a positive number down to a step and precision using Decimal arithmetic."""

    value_decimal = _to_decimal(value)
    step_decimal = _to_decimal(step)
    steps = (value_decimal / step_decimal).to_integral_value(rounding=ROUND_DOWN)
    normalized = steps * step_decimal
    if precision < 0:
        raise ValueError("precision must be >= 0.")
    quantum = Decimal("1").scaleb(-precision)
    return float(normalized.quantize(quantum, rounding=ROUND_DOWN))


def _to_decimal(value: float) -> Decimal:
    """Convert float input to Decimal through its string form."""

    return Decimal(str(value))
