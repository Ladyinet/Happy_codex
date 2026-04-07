"""Fail-safe Telegram notifier for dry_run events and local subscriber management."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Protocol

import aiohttp

from bot.storage.models import EventRecord, EventType, SubscriberRecord
from bot.utils.time_utils import now_utc


class SubscriberStorageProtocol(Protocol):
    """Minimal subscriber storage API used by the notifier."""

    async def add_subscriber(self, subscriber: SubscriberRecord) -> None:
        """Create or reactivate one subscriber."""

    async def deactivate_subscriber(self, chat_id: int) -> None:
        """Deactivate one subscriber."""

    async def list_active_subscribers(self) -> list[SubscriberRecord]:
        """Return active subscribers."""


MessageSender = Callable[[int, str], Awaitable[None]]


class TelegramNotifier:
    """Broadcasts structured dry_run events without becoming a hard pipeline dependency."""

    def __init__(
        self,
        *,
        storage: SubscriberStorageProtocol,
        bot_token: str | None,
        enabled: bool = True,
        max_messages_per_second: int = 10,
        sender: MessageSender | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.storage = storage
        self.bot_token = bot_token
        self.enabled = enabled
        self.max_messages_per_second = max_messages_per_second
        self.sender = sender
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_sent_at: float | None = None

    async def send_message(self, chat_id: int, text: str) -> bool:
        """Send one Telegram message safely and return whether it was accepted by the transport."""

        if not self.enabled:
            return False

        send_impl = self.sender or self._send_via_http
        try:
            await self._throttle()
            await send_impl(chat_id, text)
            self._last_sent_at = self.monotonic()
            return True
        except Exception:
            return False

    async def broadcast(self, text: str) -> int:
        """Send one message to all active subscribers and return the number of successful sends."""

        subscribers = await self.storage.list_active_subscribers()
        delivered = 0
        for subscriber in subscribers:
            success = await self.send_message(subscriber.chat_id, text)
            if success:
                delivered += 1
        return delivered

    async def register_user(self, chat_id: int, username: str | None, first_name: str | None) -> None:
        """Create or reactivate a Telegram subscriber in local storage."""

        await self.storage.add_subscriber(
            SubscriberRecord(
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                created_at=now_utc(),
                is_active=True,
            )
        )

    async def remove_user(self, chat_id: int) -> None:
        """Deactivate a Telegram subscriber in local storage."""

        await self.storage.deactivate_subscriber(chat_id)

    async def broadcast_event(self, event: EventRecord) -> int:
        """Format and broadcast one structured event safely."""

        return await self.broadcast(self.format_event_message(event))

    @staticmethod
    def format_event_message(event: EventRecord) -> str:
        """Return a human-readable Telegram message for one dry_run/local event."""

        lines = [
            f"[{event.mode.value.upper()}] {event.event_type.value}",
            f"{event.symbol} {event.timeframe}",
        ]
        if event.price is not None:
            lines.append(f"price: {event.price}")
        if event.qty is not None:
            lines.append(f"qty: {event.qty}")
        if event.position_size is not None:
            lines.append(f"position_size: {event.position_size}")
        if event.avg_price is not None:
            lines.append(f"avg_price: {event.avg_price}")
        if event.cycle_id is not None:
            lines.append(f"cycle_id: {event.cycle_id}")
        if event.reason:
            lines.append(f"reason: {event.reason}")
        if event.event_type == EventType.SAFE_STOP:
            lines.append("status: SAFE_STOP")
        return "\n".join(lines)

    async def _throttle(self) -> None:
        if self.max_messages_per_second <= 0 or self._last_sent_at is None:
            return
        minimum_interval = 1 / self.max_messages_per_second
        elapsed = self.monotonic() - self._last_sent_at
        if elapsed < minimum_interval:
            await self.sleep(minimum_interval - elapsed)

    async def _send_via_http(self, chat_id: int, text: str) -> None:
        """Send one message via the Telegram Bot API."""

        if not self.bot_token:
            raise RuntimeError("Telegram bot token is not configured.")

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0)) as session:
            async with session.post(url, json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(f"Telegram sendMessage failed with HTTP {response.status}: {body}")
