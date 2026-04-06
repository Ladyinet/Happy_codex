"""Pure local order lifecycle manager for v1."""

from __future__ import annotations

from dataclasses import dataclass, replace

from bot.config import BotMode
from bot.storage.models import NormalizedOrder, OrderIntent, OrderRecord, OrderStatus
from bot.utils.time_utils import now_utc
from bot.utils.ids import new_id


ALLOWED_ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.SENT, OrderStatus.CANCELED, OrderStatus.REJECTED},
    OrderStatus.SENT: {
        OrderStatus.ACKED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.ACKED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.UNKNOWN,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.UNKNOWN: {
        OrderStatus.ACKED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
    },
}


class OrderManager:
    """Owns order state machine, reconcile flow, and executor-to-storage wiring."""

    @dataclass(slots=True)
    class TransitionResult:
        """Result of one local state transition."""

        success: bool
        order: OrderRecord
        safe_stop_required: bool = False
        reason: str | None = None

    def create_order_record(
        self,
        *,
        mode: BotMode,
        intent: OrderIntent,
        normalized_order: NormalizedOrder,
    ) -> OrderRecord:
        """Build a NEW order record from one strategy intent."""

        timestamp = now_utc()
        return OrderRecord(
            mode=mode,
            order_id=new_id("order"),
            client_order_id=intent.client_order_id or intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            intent_type=intent.intent_type,
            status=OrderStatus.NEW,
            requested_qty=intent.qty,
            requested_price=intent.price,
            normalized_qty=normalized_order.qty,
            normalized_price=normalized_order.price,
            filled_qty=0.0,
            avg_fill_price=None,
            cycle_id=intent.cycle_id,
            reason=intent.reason,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def mark_sent(self, order: OrderRecord) -> TransitionResult:
        """Move NEW order to SENT."""

        return self._transition(order, OrderStatus.SENT)

    def mark_acked(self, order: OrderRecord) -> TransitionResult:
        """Move SENT/UNKNOWN order to ACKED."""

        return self._transition(order, OrderStatus.ACKED)

    def mark_partial_fill(
        self,
        order: OrderRecord,
        *,
        fill_qty: float,
        fill_price: float,
    ) -> TransitionResult:
        """Apply a PARTIALLY_FILLED transition with cumulative filled quantity."""

        total_filled = order.filled_qty + fill_qty
        if fill_qty <= 0:
            return self.TransitionResult(False, order, True, "partial fill quantity must be > 0")
        if order.normalized_qty is not None and total_filled > order.normalized_qty + 1e-12:
            return self.TransitionResult(False, order, True, "partial fill exceeds normalized quantity")
        return self._transition(
            order,
            OrderStatus.PARTIALLY_FILLED,
            filled_qty=total_filled,
            avg_fill_price=fill_price,
        )

    def mark_filled(
        self,
        order: OrderRecord,
        *,
        fill_price: float,
        filled_qty: float | None = None,
    ) -> TransitionResult:
        """Move order to FILLED using the provided or normalized quantity."""

        final_qty = filled_qty if filled_qty is not None else (order.normalized_qty or order.requested_qty)
        if final_qty <= 0:
            return self.TransitionResult(False, order, True, "filled quantity must be > 0")
        return self._transition(
            order,
            OrderStatus.FILLED,
            filled_qty=final_qty,
            avg_fill_price=fill_price,
        )

    def mark_rejected(self, order: OrderRecord, *, reason: str | None = None) -> TransitionResult:
        """Move order to REJECTED."""

        return self._transition(order, OrderStatus.REJECTED, last_error=reason)

    def mark_canceled(self, order: OrderRecord, *, reason: str | None = None) -> TransitionResult:
        """Move order to CANCELED."""

        return self._transition(order, OrderStatus.CANCELED, last_error=reason)

    def mark_unknown(self, order: OrderRecord, *, reason: str | None = None) -> TransitionResult:
        """Move order to UNKNOWN for later reconciliation."""

        return self._transition(order, OrderStatus.UNKNOWN, last_error=reason)

    def _transition(
        self,
        order: OrderRecord,
        next_status: OrderStatus,
        *,
        filled_qty: float | None = None,
        avg_fill_price: float | None = None,
        last_error: str | None = None,
    ) -> TransitionResult:
        """Apply one explicit lifecycle transition if it is allowed."""

        allowed = ALLOWED_ORDER_TRANSITIONS.get(order.status, set())
        if next_status not in allowed:
            return self.TransitionResult(
                success=False,
                order=order,
                safe_stop_required=True,
                reason=f"invalid transition: {order.status.value} -> {next_status.value}",
            )

        updated = replace(
            order,
            status=next_status,
            filled_qty=filled_qty if filled_qty is not None else order.filled_qty,
            avg_fill_price=avg_fill_price if avg_fill_price is not None else order.avg_fill_price,
            last_error=last_error,
            updated_at=now_utc(),
        )
        return self.TransitionResult(success=True, order=updated)
