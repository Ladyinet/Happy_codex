"""Even-bar skeleton tests."""

from bot.config import EvenBarAnchorMode, Settings


def test_even_bar_default_is_utc_day_start() -> None:
    """The default even-bar anchor must remain utc_day_start."""
    assert Settings().even_bar_anchor_mode == EvenBarAnchorMode.UTC_DAY_START
