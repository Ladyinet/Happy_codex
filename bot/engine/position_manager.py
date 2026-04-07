"""Pure local position and LIFO lot-book logic for v1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from bot.storage.models import BotState, Lot


def next_open_sequence(lots: list[Lot]) -> int:
    """Return the next open_sequence value for a new lot."""

    if not lots:
        return 0
    return max(lot.open_sequence or 0 for lot in lots) + 1


def recalculate_position_fields(
    state: BotState,
    *,
    last_fill_price: float | None = None,
    next_level_price: float | None = None,
) -> BotState:
    """Recalculate aggregate position fields from the current lot-book."""

    updated = deepcopy(state)
    updated.lots = sorted(updated.lots, key=lambda lot: lot.open_sequence or 0)
    updated.pos_size_abs = sum(lot.qty for lot in updated.lots)
    updated.pos_proceeds_usdt = sum(lot.qty * lot.entry_price for lot in updated.lots)
    updated.avg_price = (
        updated.pos_proceeds_usdt / updated.pos_size_abs if updated.pos_size_abs > 0 else 0.0
    )
    if last_fill_price is not None:
        updated.last_fill_price = last_fill_price
    if updated.pos_size_abs == 0:
        updated.next_level_price = None
    elif next_level_price is not None:
        updated.next_level_price = next_level_price
    return updated


class PositionManager:
    """Maintains local position state and LIFO lot ordering."""

    def add_short_lot(
        self,
        state: BotState,
        *,
        qty: float,
        entry_price: float,
        tag: str,
        created_at: datetime,
        lot_id: str,
        source_order_id: str | None = None,
        next_level_price: float | None = None,
    ) -> BotState:
        """Append a new short lot and recalculate aggregate state."""

        updated = deepcopy(state)
        updated.lots.append(
            Lot(
                id=lot_id,
                qty=qty,
                entry_price=entry_price,
                tag=tag,
                usdt_value=qty * entry_price,
                created_at=created_at,
                open_sequence=next_open_sequence(updated.lots),
                source_order_id=source_order_id,
            )
        )
        updated.num_sells += 1
        if updated.cycle_base_qty == 0:
            updated.cycle_base_qty = qty
        return recalculate_position_fields(
            updated,
            last_fill_price=entry_price,
            next_level_price=next_level_price,
        )

    def get_last_lot(self, state: BotState) -> Lot | None:
        """Return the newest currently open lot."""

        if not state.lots:
            return None
        return max(state.lots, key=lambda lot: lot.open_sequence or 0)

    def close_last_lot(
        self,
        state: BotState,
        *,
        close_qty: float,
        close_price: float,
        next_level_price: float | None = None,
    ) -> BotState:
        """Close the newest lot fully or partially using LIFO ordering."""

        if close_qty <= 0:
            raise ValueError("close_qty must be > 0.")

        updated = deepcopy(state)
        last_lot = self.get_last_lot(updated)
        if last_lot is None:
            raise ValueError("Cannot close a lot when no lots are open.")
        if close_qty > last_lot.qty:
            raise ValueError("close_qty cannot exceed the quantity of the last lot.")

        if close_qty == last_lot.qty:
            updated.lots = [lot for lot in updated.lots if lot.id != last_lot.id]
        else:
            for lot in updated.lots:
                if lot.id == last_lot.id:
                    lot.qty = round(last_lot.qty - close_qty, 12)
                    lot.usdt_value = lot.qty * lot.entry_price
                    break

        return recalculate_position_fields(
            updated,
            last_fill_price=close_price,
            next_level_price=next_level_price,
        )

    def close_all(self, state: BotState, *, close_price: float) -> BotState:
        """Close all open lots without making a trading decision."""

        updated = deepcopy(state)
        updated.lots = []
        return recalculate_position_fields(updated, last_fill_price=close_price, next_level_price=None)

    def reset_cycle(self, state: BotState) -> BotState:
        """Reset cycle-scoped fields after a full close."""

        updated = deepcopy(state)
        updated.lots = []
        updated.pos_size_abs = 0.0
        updated.pos_proceeds_usdt = 0.0
        updated.avg_price = 0.0
        updated.num_sells = 0
        updated.last_fill_price = None
        updated.next_level_price = None
        updated.trailing_active = False
        updated.trailing_min = None
        updated.cycle_base_qty = 0.0
        updated.reset_cycle = True
        updated.fills_this_bar = 0
        updated.subcovers_this_bar = 0
        return updated
