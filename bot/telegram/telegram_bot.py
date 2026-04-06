"""Telegram command skeleton backed by local state and storage only."""

from __future__ import annotations


class TelegramBotController:
    """Serves read-only commands from local runtime state and SQLite storage."""

    async def start(self) -> None:
        """Start command polling once wiring is implemented."""
        raise NotImplementedError

    async def handle_start(self, chat_id: int, username: str | None, first_name: str | None) -> str:
        """Register a Telegram subscriber in local storage."""
        raise NotImplementedError

    async def handle_stop(self, chat_id: int) -> str:
        """Deactivate a Telegram subscriber in local storage."""
        raise NotImplementedError

    async def handle_status(self, chat_id: int) -> str:
        """Return status strictly from runtime state and local storage."""
        raise NotImplementedError

    async def handle_position(self, chat_id: int) -> str:
        """Return local position data without querying the exchange."""
        raise NotImplementedError

    async def handle_pnl(self, chat_id: int) -> str:
        """Return local PnL data without querying the exchange."""
        raise NotImplementedError

    async def handle_sync(self, chat_id: int) -> str:
        """Trigger a future explicit sync flow with the exchange."""
        raise NotImplementedError
