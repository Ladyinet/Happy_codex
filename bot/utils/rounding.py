"""Shared order-normalization skeleton for dry_run and future live mode."""

from __future__ import annotations

from bot.config import InvalidOrderPolicy
from bot.storage.models import InstrumentConstraints, NormalizedOrder


class OrderNormalizer:
    """Normalizes order price and quantity without increasing intended risk."""

    def __init__(self, invalid_order_policy: InvalidOrderPolicy) -> None:
        self.invalid_order_policy = invalid_order_policy

    def normalize_order(
        self,
        symbol: str,
        price: float | None,
        qty: float,
        constraints: InstrumentConstraints,
    ) -> NormalizedOrder:
        """Apply one shared normalization path for all execution modes."""
        raise NotImplementedError
