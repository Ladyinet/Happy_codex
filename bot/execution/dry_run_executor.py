"""Dry-run executor using local virtual execution only."""

from __future__ import annotations

from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.signals import Candle
from bot.execution.base_executor import BaseExecutor, ExecutionResult
from bot.execution.order_manager import OrderManager
from bot.storage.models import BotState, EventRecord, EventType, FillRecord, InstrumentConstraints, OrderIntent, OrderIntentType
from bot.utils.rounding import OrderNormalizer


class DryRunExecutor(BaseExecutor):
    """Executes normalized intents against local virtual state without exchange orders."""

    def __init__(
        self,
        *,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        position_manager: PositionManager,
        order_normalizer: OrderNormalizer,
    ) -> None:
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.order_normalizer = order_normalizer

    async def execute_intent(
        self,
        intent: OrderIntent,
        state: BotState,
        candle: Candle,
        constraints: InstrumentConstraints,
        seen_intent_keys: set[str] | None = None,
    ) -> ExecutionResult:
        """Simulate execution using the shared normalization path and close-only fills."""

        risk_result = self.risk_manager.check_intent(
            state=state,
            intent=intent,
            candle=candle,
            seen_intent_keys=seen_intent_keys,
        )
        if not risk_result.allow:
            return ExecutionResult(
                updated_state=state,
                risk_result=risk_result,
                blocked=True,
                safe_stop_required=risk_result.safe_stop_required,
                reason=risk_result.reason,
            )

        normalized = self.order_normalizer.normalize_order(
            symbol=intent.symbol,
            price=intent.price if intent.price is not None else candle.close,
            qty=intent.qty,
            constraints=constraints,
        )
        normalized_check = self.risk_manager.check_normalized_order(normalized)
        if not normalized_check.allow:
            return ExecutionResult(
                updated_state=state,
                risk_result=normalized_check,
                blocked=True,
                safe_stop_required=normalized_check.safe_stop_required,
                reason=normalized_check.reason,
            )

        order = self.order_manager.create_order_record(
            mode=state.mode,
            intent=intent,
            normalized_order=normalized,
        )
        sent_result = self.order_manager.mark_sent(order)
        if not sent_result.success:
            return ExecutionResult(
                order=sent_result.order,
                updated_state=state,
                safe_stop_required=sent_result.safe_stop_required,
                reason=sent_result.reason,
            )
        acked_result = self.order_manager.mark_acked(sent_result.order)
        if not acked_result.success:
            return ExecutionResult(
                order=acked_result.order,
                updated_state=state,
                safe_stop_required=acked_result.safe_stop_required,
                reason=acked_result.reason,
            )
        filled_result = self.order_manager.mark_filled(
            acked_result.order,
            fill_price=candle.close,
            filled_qty=normalized.qty,
        )
        if not filled_result.success:
            return ExecutionResult(
                order=filled_result.order,
                updated_state=state,
                safe_stop_required=filled_result.safe_stop_required,
                reason=filled_result.reason,
            )

        fill = FillRecord(
            fill_id=None,
            order_id=filled_result.order.order_id,
            client_order_id=filled_result.order.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            price=candle.close,
            qty=normalized.qty,
            fee=None,
            occurred_at=candle.close_time,
            raw_status="dry_run_fill",
        )

        updated_state = self._apply_fill_to_state(
            state=state,
            intent=intent,
            fill=fill,
        )
        events = [
            EventRecord(
                event_id=f"{intent.intent_type.value}:{candle.close_time.isoformat()}",
                event_type=_event_type_for_intent(intent.intent_type),
                mode=state.mode,
                symbol=state.symbol,
                timeframe=state.timeframe,
                reason=intent.reason,
                created_at=candle.close_time,
                price=fill.price,
                qty=fill.qty,
                position_size=updated_state.pos_size_abs,
                avg_price=updated_state.avg_price,
                cycle_id=updated_state.cycle_id,
            )
        ]
        return ExecutionResult(
            order=filled_result.order,
            fills=[fill],
            events=events,
            updated_state=updated_state,
            risk_result=risk_result,
            blocked=False,
            safe_stop_required=False,
            reason=None,
        )

    def _apply_fill_to_state(
        self,
        *,
        state: BotState,
        intent: OrderIntent,
        fill: FillRecord,
    ) -> BotState:
        if intent.intent_type in {OrderIntentType.FIRST_SHORT, OrderIntentType.DCA_SHORT}:
            updated = self.position_manager.add_short_lot(
                state,
                qty=fill.qty,
                entry_price=fill.price,
                tag=intent.intent_type.value,
                created_at=fill.occurred_at,
                lot_id=intent.intent_id,
            )
            updated.orders_last_3min = [*state.orders_last_3min, fill.occurred_at]
            updated.last_candle_time = fill.occurred_at
            updated.fills_this_bar = state.fills_this_bar + 1
            updated.reset_cycle = False
            return updated

        if intent.intent_type == OrderIntentType.SUB_COVER:
            updated = self.position_manager.close_last_lot(
                state,
                close_qty=fill.qty,
                close_price=fill.price,
            )
            updated.orders_last_3min = [*state.orders_last_3min, fill.occurred_at]
            updated.last_candle_time = fill.occurred_at
            updated.subcovers_this_bar = state.subcovers_this_bar + 1
            return updated

        updated = self.position_manager.reset_cycle(
            self.position_manager.close_all(state, close_price=fill.price)
        )
        updated.orders_last_3min = [*state.orders_last_3min, fill.occurred_at]
        updated.last_candle_time = fill.occurred_at
        return updated


def _event_type_for_intent(intent_type: OrderIntentType) -> EventType:
    return {
        OrderIntentType.FIRST_SHORT: EventType.FIRST_SHORT,
        OrderIntentType.DCA_SHORT: EventType.DCA_SHORT,
        OrderIntentType.SUB_COVER: EventType.SUB_COVER,
        OrderIntentType.FULL_COVER: EventType.FULL_COVER,
        OrderIntentType.TRAILING_TP: EventType.TRAILING_TP,
    }[intent_type]
