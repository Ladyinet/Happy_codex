"""Telegram notification skeleton with fail-safe behavior."""

from __future__ import annotations

from bot.storage.models import EventRecord


class TelegramNotifier:
    """Broadcasts structured events without becoming a hard dependency of the bot."""

    async def send_message(self, text: str) -> None:
        """Send one raw Telegram message."""
        raise NotImplementedError

    async def broadcast_event(self, event: EventRecord) -> None:
        """Send one structured event to all active subscribers."""
        raise NotImplementedError
