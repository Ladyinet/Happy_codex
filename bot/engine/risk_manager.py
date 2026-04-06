"""Risk and safe-stop skeleton for v1."""

from __future__ import annotations

from bot.engine.signals import Candle
from bot.storage.models import BotState, OrderIntent


class RiskManager:
    """Checks order limits, safe-stop rules, and duplicate-execution risk."""

    def can_create_order(self, state: BotState, intent: OrderIntent, candle: Candle) -> bool:
        """Return whether an order intent is allowed to proceed."""
        raise NotImplementedError

    def should_enter_safe_stop(self, state: BotState, reason: str) -> bool:
        """Return whether the bot must move into safe-stop."""
        raise NotImplementedError
