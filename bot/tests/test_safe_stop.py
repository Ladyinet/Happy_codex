"""Safe-stop skeleton tests."""

from bot.storage.models import EventType


def test_safe_stop_event_type_exists() -> None:
    """The SAFE_STOP event type should be defined at skeleton level."""
    assert EventType.SAFE_STOP == "SAFE_STOP"
