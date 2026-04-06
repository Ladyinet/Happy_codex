"""Pure bar-close strategy logic for v1."""

from __future__ import annotations

from copy import deepcopy

from bot.config import Settings, SubcoverConfirmMode, TouchMode
from bot.engine.position_manager import PositionManager
from bot.engine.signals import Candle, StrategyContext, StrategyDecision
from bot.storage.models import BotState, EventRecord, EventType, OrderIntent, OrderIntentType, OrderSide


class StrategyEngine:
    """Evaluates one closed bar and returns intents, events, and a state patch."""

    def __init__(self, position_manager: PositionManager | None = None) -> None:
        self.position_manager = position_manager or PositionManager()

    def evaluate_bar(self, context: StrategyContext) -> StrategyDecision:
        """Process one closed bar using the required v1 priority order."""

        candle = context.candle
        settings = context.settings
        state = deepcopy(context.state)
        state.last_candle_time = candle.close_time

        invalid_reason = _invalid_state_reason(state)
        if invalid_reason is not None:
            state.safe_stop_active = True
            state.safe_stop_reason = invalid_reason
            return StrategyDecision(
                updated_state=state,
                safe_stop_required=True,
                safe_stop_reason=invalid_reason,
                events=[_make_event(state=state, candle=candle, event_type=EventType.SAFE_STOP, reason=invalid_reason)],
            )

        if not context.even_bar_allowed:
            return StrategyDecision(updated_state=state, blocked_by_even_bar=True)

        if state.pos_size_abs == 0 or not state.lots:
            return self._evaluate_first_short(state=state, candle=candle, settings=settings)

        tp_price = _full_tp_price(state=state, settings=settings)
        tp_touch = _touches_downside(candle=candle, level=tp_price, touch_mode=settings.touch_mode)
        tp_confirmed = tp_touch and (
            not settings.require_close_below_full_tp or candle.close <= tp_price
        )
        blocked_by_tp_touch = tp_touch and settings.block_dca_on_tp_touch and not tp_confirmed

        if tp_confirmed:
            updated_state = self.position_manager.reset_cycle(
                self.position_manager.close_all(state, close_price=candle.close)
            )
            return StrategyDecision(
                order_intents=[
                    _make_intent(
                        state=state,
                        candle=candle,
                        intent_type=OrderIntentType.FULL_COVER,
                        side=OrderSide.BUY,
                        qty=state.pos_size_abs,
                        reason="full_tp",
                    )
                ],
                events=[
                    _make_event(
                        state=state,
                        candle=candle,
                        event_type=EventType.FULL_COVER,
                        reason="full_tp",
                        qty=state.pos_size_abs,
                    )
                ],
                updated_state=updated_state,
                full_tp_triggered=True,
                blocked_by_tp_touch=blocked_by_tp_touch,
            )

        trailing_state = deepcopy(state)
        trailing_just_activated = False
        if tp_touch and not trailing_state.trailing_active and settings.callback_percent > 0:
            trailing_state.trailing_active = True
            trailing_state.trailing_min = _downside_reference(candle, settings.touch_mode)
            trailing_just_activated = True
        elif trailing_state.trailing_active and trailing_state.trailing_min is not None:
            trailing_state.trailing_min = min(
                trailing_state.trailing_min,
                _downside_reference(candle, settings.touch_mode),
            )

        if trailing_state.trailing_active and trailing_state.trailing_min is not None and not trailing_just_activated:
            trail_stop = trailing_state.trailing_min * (1 + settings.callback_percent / 100)
            if candle.close >= trail_stop:
                updated_state = self.position_manager.reset_cycle(
                    self.position_manager.close_all(trailing_state, close_price=candle.close)
                )
                return StrategyDecision(
                    order_intents=[
                        _make_intent(
                            state=state,
                            candle=candle,
                            intent_type=OrderIntentType.TRAILING_TP,
                            side=OrderSide.BUY,
                            qty=state.pos_size_abs,
                            reason="trailing_exit",
                        )
                    ],
                    events=[
                        _make_event(
                            state=state,
                            candle=candle,
                            event_type=EventType.TRAILING_TP,
                            reason="trailing_exit",
                            qty=state.pos_size_abs,
                        )
                    ],
                    updated_state=updated_state,
                    trailing_exit_triggered=True,
                    blocked_by_tp_touch=blocked_by_tp_touch,
                )

        subcover_result = self._evaluate_subcover(
            state=trailing_state,
            candle=candle,
            settings=settings,
            blocked_by_tp_touch=blocked_by_tp_touch,
        )
        if subcover_result is not None:
            return subcover_result

        dca_result = self._evaluate_dca(
            state=trailing_state,
            candle=candle,
            settings=settings,
            blocked_by_tp_touch=blocked_by_tp_touch,
        )
        if dca_result is not None:
            return dca_result

        return StrategyDecision(updated_state=trailing_state, blocked_by_tp_touch=blocked_by_tp_touch)

    def _evaluate_first_short(self, *, state: BotState, candle: Candle, settings: Settings) -> StrategyDecision:
        qty = _base_order_qty(settings=settings, close_price=candle.close)
        if qty <= 0:
            reason = "base order quantity is not positive"
            state.safe_stop_active = True
            state.safe_stop_reason = reason
            return StrategyDecision(
                updated_state=state,
                safe_stop_required=True,
                safe_stop_reason=reason,
                events=[_make_event(state=state, candle=candle, event_type=EventType.SAFE_STOP, reason=reason)],
            )

        updated_state = self.position_manager.add_short_lot(
            state,
            qty=qty,
            entry_price=candle.close,
            tag="FIRST_SHORT",
            created_at=candle.close_time,
            lot_id=_intent_key(OrderIntentType.FIRST_SHORT, candle),
            next_level_price=_next_level_price(last_fill_price=candle.close, next_sell_number=2),
        )
        return StrategyDecision(
            order_intents=[
                _make_intent(
                    state=state,
                    candle=candle,
                    intent_type=OrderIntentType.FIRST_SHORT,
                    side=OrderSide.SELL,
                    qty=qty,
                    reason="first_short",
                )
            ],
            events=[
                _make_event(
                    state=updated_state,
                    candle=candle,
                    event_type=EventType.FIRST_SHORT,
                    reason="first_short",
                    qty=qty,
                )
            ],
            updated_state=updated_state,
        )

    def _evaluate_subcover(
        self,
        *,
        state: BotState,
        candle: Candle,
        settings: Settings,
        blocked_by_tp_touch: bool,
    ) -> StrategyDecision | None:
        if state.num_sells <= 5:
            return None
        last_lot = self.position_manager.get_last_lot(state)
        if last_lot is None:
            return None

        last_lot_tp = last_lot.entry_price * (1 - settings.sub_sell_tp_percent / 100)
        if not _touches_downside(candle=candle, level=last_lot_tp, touch_mode=settings.touch_mode):
            return None
        if settings.subcover_confirm_mode == SubcoverConfirmMode.BREAKEVEN and candle.close > last_lot.entry_price:
            return None
        if settings.subcover_confirm_mode == SubcoverConfirmMode.SUBCOVER_TP and candle.close > last_lot_tp:
            return None

        updated_state = self.position_manager.close_last_lot(
            state,
            close_qty=last_lot.qty,
            close_price=candle.close,
        )
        return StrategyDecision(
            order_intents=[
                _make_intent(
                    state=state,
                    candle=candle,
                    intent_type=OrderIntentType.SUB_COVER,
                    side=OrderSide.BUY,
                    qty=last_lot.qty,
                    reason="subcover",
                )
            ],
            events=[
                _make_event(
                    state=updated_state,
                    candle=candle,
                    event_type=EventType.SUB_COVER,
                    reason="subcover",
                    qty=last_lot.qty,
                )
            ],
            updated_state=updated_state,
            subcover_triggered=True,
            blocked_by_tp_touch=blocked_by_tp_touch,
        )

    def _evaluate_dca(
        self,
        *,
        state: BotState,
        candle: Candle,
        settings: Settings,
        blocked_by_tp_touch: bool,
    ) -> StrategyDecision | None:
        if blocked_by_tp_touch:
            return None
        if state.num_sells >= settings.margin_call_limit:
            return None
        if state.next_level_price is None:
            return None
        if not _touches_upside(candle=candle, level=state.next_level_price, touch_mode=settings.touch_mode):
            return None

        next_sell_number = state.num_sells + 1
        qty = _dca_qty(
            state=state,
            settings=settings,
            close_price=candle.close,
            next_sell_number=next_sell_number,
        )
        if qty <= 0:
            reason = "dca quantity is not positive"
            invalid_state = deepcopy(state)
            invalid_state.safe_stop_active = True
            invalid_state.safe_stop_reason = reason
            return StrategyDecision(
                updated_state=invalid_state,
                safe_stop_required=True,
                safe_stop_reason=reason,
                events=[_make_event(state=invalid_state, candle=candle, event_type=EventType.SAFE_STOP, reason=reason)],
            )

        updated_state = self.position_manager.add_short_lot(
            state,
            qty=qty,
            entry_price=candle.close,
            tag=f"DCA_{next_sell_number}",
            created_at=candle.close_time,
            lot_id=_intent_key(OrderIntentType.DCA_SHORT, candle),
            next_level_price=_next_level_price(last_fill_price=candle.close, next_sell_number=next_sell_number + 1),
        )
        return StrategyDecision(
            order_intents=[
                _make_intent(
                    state=state,
                    candle=candle,
                    intent_type=OrderIntentType.DCA_SHORT,
                    side=OrderSide.SELL,
                    qty=qty,
                    reason="dca",
                )
            ],
            events=[
                _make_event(
                    state=updated_state,
                    candle=candle,
                    event_type=EventType.DCA_SHORT,
                    reason="dca",
                    qty=qty,
                )
            ],
            updated_state=updated_state,
            dca_triggered=True,
        )


def _full_tp_price(*, state: BotState, settings: Settings) -> float:
    return state.avg_price * (1 - settings.tp_percent / 100)


def _base_order_qty(*, settings: Settings, close_price: float) -> float:
    if settings.use_equity_pct_base:
        if close_price <= 0:
            return 0.0
        notional = settings.equity_for_sizing_usdt * (settings.base_order_pct_eq / 100)
        return notional / close_price
    return settings.first_sell_qty_coin


def _dca_qty(*, state: BotState, settings: Settings, close_price: float, next_sell_number: int) -> float:
    base_qty = state.cycle_base_qty if state.cycle_base_qty > 0 else _base_order_qty(settings=settings, close_price=close_price)
    return base_qty * _dca_multiplier(next_sell_number)


def _dca_multiplier(next_sell_number: int) -> float:
    return {
        2: 1.5,
        3: 1.0,
        4: 2.0,
        5: 3.5,
    }.get(next_sell_number, 1.0)


def _next_level_price(*, last_fill_price: float, next_sell_number: int) -> float:
    rise_percent = {
        2: 0.3,
        3: 0.4,
        4: 0.6,
        5: 0.8,
        6: 0.8,
    }.get(next_sell_number, 0.8)
    return last_fill_price * (1 + rise_percent / 100)


def _touches_downside(*, candle: Candle, level: float, touch_mode: TouchMode) -> bool:
    if touch_mode == TouchMode.WICK:
        return candle.low <= level
    if touch_mode == TouchMode.BODY:
        return min(candle.open, candle.close) <= level
    return candle.close <= level


def _touches_upside(*, candle: Candle, level: float, touch_mode: TouchMode) -> bool:
    if touch_mode == TouchMode.WICK:
        return candle.high >= level
    if touch_mode == TouchMode.BODY:
        return max(candle.open, candle.close) >= level
    return candle.close >= level


def _downside_reference(candle: Candle, touch_mode: TouchMode) -> float:
    if touch_mode == TouchMode.WICK:
        return candle.low
    if touch_mode == TouchMode.BODY:
        return min(candle.open, candle.close)
    return candle.close


def _invalid_state_reason(state: BotState) -> str | None:
    if state.pos_size_abs < 0 or state.avg_price < 0 or state.num_sells < 0:
        return "negative state values are not allowed"
    if state.pos_size_abs == 0 and state.lots:
        return "position size is zero while lots are still open"
    if state.pos_size_abs > 0 and not state.lots:
        return "position size is positive but no lots are stored"
    if state.lots and abs(sum(lot.qty for lot in state.lots) - state.pos_size_abs) > 1e-9:
        return "position size does not match total lot quantity"
    if state.trailing_active and state.trailing_min is None:
        return "trailing is active but trailing_min is missing"
    return None


def _intent_key(intent_type: OrderIntentType, candle: Candle) -> str:
    return f"{intent_type.value}:{candle.close_time.isoformat()}"


def _make_intent(
    *,
    state: BotState,
    candle: Candle,
    intent_type: OrderIntentType,
    side: OrderSide,
    qty: float,
    reason: str,
) -> OrderIntent:
    return OrderIntent(
        intent_id=_intent_key(intent_type, candle),
        symbol=state.symbol,
        side=side,
        intent_type=intent_type,
        qty=qty,
        price=candle.close,
        reason=reason,
        created_at=candle.close_time,
        cycle_id=state.cycle_id,
    )


def _make_event(
    *,
    state: BotState,
    candle: Candle,
    event_type: EventType,
    reason: str,
    qty: float | None = None,
) -> EventRecord:
    return EventRecord(
        event_id=f"{event_type.value}:{candle.close_time.isoformat()}",
        event_type=event_type,
        mode=state.mode,
        symbol=state.symbol,
        timeframe=state.timeframe,
        reason=reason,
        created_at=candle.close_time,
        price=candle.close,
        qty=qty,
        position_size=state.pos_size_abs,
        avg_price=state.avg_price,
        cycle_id=state.cycle_id,
    )
