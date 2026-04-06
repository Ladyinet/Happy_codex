"""Risk-manager skeleton tests."""

from bot.engine.risk_manager import RiskManager


def test_risk_manager_is_importable() -> None:
    """The risk manager skeleton should be importable."""
    assert RiskManager is not None
