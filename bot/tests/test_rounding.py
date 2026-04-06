"""Tests for the shared order normalization layer."""

from __future__ import annotations

from bot.config import InvalidOrderPolicy
from bot.storage.models import InstrumentConstraints
from bot.utils.rounding import OrderNormalizer


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


def test_safe_normalization_does_not_increase_exposure() -> None:
    """Quantity and price should be rounded down, never up."""

    normalizer = OrderNormalizer(InvalidOrderPolicy.ADJUST)
    result = normalizer.normalize_order(
        symbol="BTC-USDT",
        price=100.19,
        qty=0.0199,
        constraints=_constraints(),
    )

    assert result.is_valid is False
    assert result.price == 100.1
    assert result.qty == 0.019
    assert result.qty <= 0.0199
    assert result.price <= 100.19


def test_invalid_small_order_after_safe_rounding() -> None:
    """Orders below min_qty after safe rounding must remain invalid."""

    normalizer = OrderNormalizer(InvalidOrderPolicy.SKIP)
    result = normalizer.normalize_order(
        symbol="BTC-USDT",
        price=100.0,
        qty=0.0099,
        constraints=_constraints(),
    )

    assert result.is_valid is False
    assert result.qty == 0.009
    assert "skip:" in (result.reason or "")


def test_invalid_min_notional_order() -> None:
    """Orders below min_notional after safe normalization must remain invalid."""

    normalizer = OrderNormalizer(InvalidOrderPolicy.SAFE_STOP)
    result = normalizer.normalize_order(
        symbol="BTC-USDT",
        price=100.0,
        qty=0.05,
        constraints=_constraints(),
    )

    assert result.is_valid is False
    assert result.qty == 0.05
    assert "safe_stop:" in (result.reason or "")


def test_valid_order_remains_valid_after_normalization() -> None:
    """Orders already above minimums should normalize successfully."""

    normalizer = OrderNormalizer(InvalidOrderPolicy.ADJUST)
    result = normalizer.normalize_order(
        symbol="BTC-USDT",
        price=250.27,
        qty=0.05,
        constraints=_constraints(),
    )

    assert result.is_valid is True
    assert result.price == 250.2
    assert result.qty == 0.05
