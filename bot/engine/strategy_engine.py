"""Strategy-engine skeleton for v1."""

from __future__ import annotations

from bot.engine.signals import StrategyContext, StrategyDecision


class StrategyEngine:
    """Evaluates strategy rules and emits order intents."""

    def evaluate_bar(self, context: StrategyContext) -> StrategyDecision:
        """Process one closed bar using the mandatory single-bar priority rules."""
        raise NotImplementedError
