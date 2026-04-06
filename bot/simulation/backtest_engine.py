"""Backtest skeleton reusing the shared v1 engine stack."""

from __future__ import annotations

from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.utils.rounding import OrderNormalizer


class BacktestEngine:
    """Runs historical candles through the same shared engine and rounding layers."""

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        order_normalizer: OrderNormalizer,
    ) -> None:
        self.strategy_engine = strategy_engine
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self.order_normalizer = order_normalizer

    async def run(self) -> None:
        """Execute the backtest workflow once the runtime wiring is implemented."""
        raise NotImplementedError
