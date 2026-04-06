"""Rounding-layer skeleton tests."""

from bot.config import InvalidOrderPolicy
from bot.utils.rounding import OrderNormalizer


def test_rounding_layer_is_importable() -> None:
    """The shared normalizer skeleton should be importable."""
    assert OrderNormalizer(InvalidOrderPolicy.ADJUST) is not None
