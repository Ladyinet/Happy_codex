"""Telegram command controller backed only by local runtime state and storage."""

from __future__ import annotations

from typing import Callable

from bot.storage.models import BotState
from bot.telegram.telegram_notifier import TelegramNotifier
from bot.utils.time_utils import datetime_to_iso


class TelegramBotController:
    """Serves local dry_run commands without exchange or trading network calls."""

    def __init__(
        self,
        *,
        notifier: TelegramNotifier,
        state_getter: Callable[[], BotState],
    ) -> None:
        self.notifier = notifier
        self.state_getter = state_getter

    async def start(self) -> None:
        """Polling/runtime wiring is intentionally out of scope for dry_run v1."""

    async def handle_start(self, chat_id: int, username: str | None, first_name: str | None) -> str:
        """Register or reactivate one subscriber in local storage."""

        await self.notifier.register_user(chat_id, username, first_name)
        return "Subscription enabled for dry_run notifications."

    async def handle_stop(self, chat_id: int) -> str:
        """Deactivate one subscriber in local storage."""

        await self.notifier.remove_user(chat_id)
        return "Subscription disabled."

    async def handle_status(self, chat_id: int) -> str:
        """Return local dry_run status without querying the exchange."""

        _ = chat_id
        state = self.state_getter()
        lines = [
            f"mode: {state.mode.value}",
            f"symbol: {state.symbol}",
            f"timeframe: {state.timeframe}",
            f"last_candle_time: {datetime_to_iso(state.last_candle_time) if state.last_candle_time else 'n/a'}",
            f"safe_stop_active: {state.safe_stop_active}",
        ]
        if state.safe_stop_reason:
            lines.append(f"safe_stop_reason: {state.safe_stop_reason}")
        return "\n".join(lines)

    async def handle_position(self, chat_id: int) -> str:
        """Return local position summary without exchange access."""

        _ = chat_id
        state = self.state_getter()
        return "\n".join(
            [
                f"pos_size_abs: {state.pos_size_abs}",
                f"avg_price: {state.avg_price}",
                f"num_sells: {state.num_sells}",
                f"trailing_active: {state.trailing_active}",
            ]
        )

    async def handle_pnl(self, chat_id: int) -> str:
        """Return a limited local dry_run PnL summary."""

        _ = chat_id
        state = self.state_getter()
        return "\n".join(
            [
                "PnL summary not fully implemented yet in dry_run v1.",
                f"pos_size_abs: {state.pos_size_abs}",
                f"avg_price: {state.avg_price}",
                f"last_fill_price: {state.last_fill_price if state.last_fill_price is not None else 'n/a'}",
            ]
        )

    async def handle_sync(self, chat_id: int) -> str:
        """Return the dry_run v1 sync stub without any exchange call."""

        _ = chat_id
        return "sync not implemented in dry_run v1"
