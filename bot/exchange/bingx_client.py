"""Skeleton exchange client for future BingX integration."""

from __future__ import annotations

from bot.storage.models import FillRecord, OrderRecord


class BingXClient:
    """Placeholder client for future REST and WebSocket integration."""

    async def connect(self) -> None:
        """Open exchange connections."""
        raise NotImplementedError

    async def disconnect(self) -> None:
        """Close exchange connections."""
        raise NotImplementedError

    async def fetch_instrument_constraints(self, symbol: str) -> dict:
        """Fetch instrument metadata required for normalization."""
        raise NotImplementedError

    async def place_order(self, order: OrderRecord) -> OrderRecord:
        """Send a normalized order to the exchange in a future live implementation."""
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> None:
        """Cancel an existing exchange order."""
        raise NotImplementedError

    async def fetch_order_status(self, order_id: str) -> OrderRecord:
        """Fetch the latest order status for reconciliation."""
        raise NotImplementedError

    async def fetch_fills(self, order_id: str) -> list[FillRecord]:
        """Fetch fills associated with an order."""
        raise NotImplementedError

    async def fetch_position(self, symbol: str) -> dict:
        """Fetch the aggregate exchange position for manual sync flows."""
        raise NotImplementedError
