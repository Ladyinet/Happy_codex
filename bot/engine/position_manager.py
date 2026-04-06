"""Position and LIFO lot-book skeleton for v1."""

from __future__ import annotations

from bot.storage.models import BotState, FillRecord, Lot


class PositionManager:
    """Maintains local position state and LIFO lot ordering."""

    def apply_fill(self, state: BotState, fill: FillRecord) -> BotState:
        """Apply one fill to local position state."""
        raise NotImplementedError

    def open_lot(self, state: BotState, lot: Lot) -> BotState:
        """Append a newly opened lot to the local lot-book."""
        raise NotImplementedError

    def close_last_lot(self, state: BotState, close_qty: float, close_price: float) -> BotState:
        """Close the most recent lot using LIFO ordering."""
        raise NotImplementedError

    def reset_cycle(self, state: BotState) -> BotState:
        """Reset local cycle state after a full close."""
        raise NotImplementedError
