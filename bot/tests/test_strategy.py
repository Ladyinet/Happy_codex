"""Strategy skeleton tests."""

from bot.engine.strategy_engine import StrategyEngine


def test_strategy_engine_is_importable() -> None:
    """The shared strategy engine skeleton should be importable."""
    assert StrategyEngine is not None
