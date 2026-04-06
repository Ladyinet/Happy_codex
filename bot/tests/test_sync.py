"""Sync-policy skeleton tests."""

from bot.config import DesyncPolicy, Settings
from bot.storage.models import OrderStatus


def test_default_desync_policy_is_safe_stop() -> None:
    """The default desync policy must remain safe_stop."""
    assert Settings().desync_policy == DesyncPolicy.SAFE_STOP


def test_unknown_order_status_exists() -> None:
    """UNKNOWN order status is mandatory for the explicit order state machine."""
    assert OrderStatus.UNKNOWN == "UNKNOWN"
