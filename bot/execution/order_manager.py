"""Order lifecycle and reconciliation skeleton for v1."""

from __future__ import annotations

from bot.storage.models import OrderRecord, OrderStatus


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

    async def submit(self, order: OrderRecord) -> OrderRecord:
        """Submit one order record into the execution pipeline."""
        raise NotImplementedError

    async def transition(self, order: OrderRecord, next_status: OrderStatus) -> OrderRecord:
        """Apply one explicit lifecycle transition if it is allowed."""
        raise NotImplementedError

    async def reconcile(self, order: OrderRecord) -> OrderRecord:
        """Reconcile order state using status checks and fill history."""
        raise NotImplementedError

    async def reconcile_unknown(self, order: OrderRecord) -> OrderRecord:
        """Resolve UNKNOWN state without blind re-ordering."""
        raise NotImplementedError
