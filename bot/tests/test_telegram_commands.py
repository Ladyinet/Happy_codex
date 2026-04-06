"""Telegram command skeleton tests."""

from bot.telegram.telegram_bot import TelegramBotController


def test_telegram_controller_is_importable() -> None:
    """Telegram commands should be wired through a local controller skeleton."""
    assert TelegramBotController is not None
