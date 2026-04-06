"""Pure risk/filter layer for intent execution in v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from bot.config import InvalidOrderPolicy, Settings
from bot.engine.signals import Candle
from bot.storage.models import BotState, NormalizedOrder, OrderIntent, OrderIntentType


@dataclass(slots=True)
class RiskCheckResult:
    """Typed result of one risk/filter decision."""

    allow: bool
    reason: str | None = None
    safe_stop_required: bool = False


class RiskManager:
    """Checks rate limits, duplicate intent guards, and safe-stop conditions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def check_intent(
        self,
        *,
        state: BotState,
        intent: OrderIntent,
        candle: Candle,
        seen_intent_keys: set[str] | None = None,
    ) -> RiskCheckResult:
        """Evaluate whether an intent may proceed to normalization/execution."""

        invalid_reason = self._invalid_state_reason(state)
        if invalid_reason is not None:
            return RiskCheckResult(allow=False, reason=invalid_reason, safe_stop_required=True)

        if state.safe_stop_active:
            return RiskCheckResult(allow=False, reason="safe_stop is active", safe_stop_required=False)

        if seen_intent_keys is not None and intent.intent_id in seen_intent_keys:
            return RiskCheckResult(allow=False, reason="duplicate intent for the same bar/cycle")

        cutoff = candle.close_time - timedelta(minutes=3)
        recent_orders = [timestamp for timestamp in state.orders_last_3min if timestamp >= cutoff]
        if len(recent_orders) >= self.settings.max_orders_per_3min:
            return RiskCheckResult(allow=False, reason="max orders per 3 minutes exceeded")

        if intent.intent_type == OrderIntentType.DCA_SHORT and state.fills_this_bar >= self.settings.max_dca_per_bar:
            return RiskCheckResult(allow=False, reason="max DCA per bar exceeded")

        if intent.intent_type == OrderIntentType.SUB_COVER and state.subcovers_this_bar >= self.settings.max_subcover_per_bar:
            return RiskCheckResult(allow=False, reason="max sub-cover per bar exceeded")

        return RiskCheckResult(allow=True)

    def check_normalized_order(self, normalized_order: NormalizedOrder) -> RiskCheckResult:
        """Evaluate normalization output according to INVALID_ORDER_POLICY."""

        if normalized_order.is_valid:
            return RiskCheckResult(allow=True)

        safe_stop_required = self.settings.invalid_order_policy == InvalidOrderPolicy.SAFE_STOP
        return RiskCheckResult(
            allow=False,
            reason=normalized_order.reason or "normalized order is invalid",
            safe_stop_required=safe_stop_required,
        )

    def should_enter_safe_stop(self, state: BotState, reason: str) -> bool:
        """Return whether the bot must move into safe-stop."""

        return self._invalid_state_reason(state) is not None or bool(reason)

    @staticmethod
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
