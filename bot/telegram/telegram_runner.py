"""Aiogram long-polling runner for local dry_run Telegram commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings, load_settings
from bot.storage.models import BotState
from bot.telegram.telegram_bot import TelegramBotController
from bot.telegram.telegram_notifier import TelegramNotifier


class TelegramRunnerStorageProtocol(Protocol):
    """Minimal storage API required by the Telegram polling runner."""

    async def init_db(self) -> None:
        """Initialize the local storage if needed."""

    async def load_bot_state(self, mode, symbol: str, timeframe: str) -> BotState | None:
        """Load the latest persisted bot state snapshot."""

    async def add_subscriber(self, subscriber) -> None:
        """Create or reactivate a subscriber."""

    async def deactivate_subscriber(self, chat_id: int) -> None:
        """Deactivate a subscriber."""

    async def list_active_subscribers(self):
        """Return active subscribers."""


StateProvider = Callable[[], BotState | Awaitable[BotState]]


def build_storage_backed_state_provider(
    *,
    settings: Settings,
    storage: TelegramRunnerStorageProtocol,
    runtime_state_getter: Callable[[], BotState | None] | None = None,
) -> StateProvider:
    """Return a state provider that prefers injected runtime state and falls back to SQLite."""

    async def _provider() -> BotState:
        if runtime_state_getter is not None:
            runtime_state = runtime_state_getter()
            if runtime_state is not None:
                return runtime_state

        restored = await storage.load_bot_state(settings.mode, settings.symbol, settings.timeframe)
        if restored is not None:
            return restored

        return BotState(mode=settings.mode, symbol=settings.symbol, timeframe=settings.timeframe)

    return _provider


def build_telegram_controller(
    *,
    settings: Settings,
    storage: TelegramRunnerStorageProtocol,
    state_provider: StateProvider,
) -> TelegramBotController:
    """Create the Telegram notifier/controller pair for dry_run polling."""

    notifier = TelegramNotifier(
        storage=storage,
        bot_token=settings.telegram_bot_token,
        enabled=settings.telegram_enabled,
        max_messages_per_second=settings.telegram_max_messages_per_second,
    )
    return TelegramBotController(notifier=notifier, state_getter=state_provider)


async def handle_start_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /start command safely."""

    text = await controller.handle_start(
        _chat_id(message),
        _username(message),
        _first_name(message),
    )
    await message.answer(text)


async def handle_stop_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /stop command safely."""

    text = await controller.handle_stop(_chat_id(message))
    await message.answer(text)


async def handle_status_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /status command safely."""

    text = await controller.handle_status(_chat_id(message))
    await message.answer(text)


async def handle_position_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /position command safely."""

    text = await controller.handle_position(_chat_id(message))
    await message.answer(text)


async def handle_pnl_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /pnl command safely."""

    text = await controller.handle_pnl(_chat_id(message))
    await message.answer(text)


async def handle_sync_command(message: Message, controller: TelegramBotController) -> None:
    """Handle the /sync command safely."""

    text = await controller.handle_sync(_chat_id(message))
    await message.answer(text)


def build_telegram_router(controller: TelegramBotController) -> Router:
    """Build the root aiogram router for the dry_run Telegram commands."""

    router = Router(name="dry_run_telegram")

    @router.message(Command("start"))
    async def _start(message: Message) -> None:
        await _run_handler(message, controller, handle_start_command)

    @router.message(Command("stop"))
    async def _stop(message: Message) -> None:
        await _run_handler(message, controller, handle_stop_command)

    @router.message(Command("status"))
    async def _status(message: Message) -> None:
        await _run_handler(message, controller, handle_status_command)

    @router.message(Command("position"))
    async def _position(message: Message) -> None:
        await _run_handler(message, controller, handle_position_command)

    @router.message(Command("pnl"))
    async def _pnl(message: Message) -> None:
        await _run_handler(message, controller, handle_pnl_command)

    @router.message(Command("sync"))
    async def _sync(message: Message) -> None:
        await _run_handler(message, controller, handle_sync_command)

    return router


def build_telegram_dispatcher(controller: TelegramBotController) -> Dispatcher:
    """Build the root aiogram dispatcher with the dry_run router attached."""

    dispatcher = Dispatcher()
    dispatcher.include_router(build_telegram_router(controller))
    return dispatcher


async def run_telegram_polling(
    *,
    settings: Settings | None = None,
    storage: TelegramRunnerStorageProtocol | None = None,
    state_provider: StateProvider | None = None,
    controller: TelegramBotController | None = None,
    dispatcher: Dispatcher | None = None,
    bot: Bot | None = None,
) -> bool:
    """Run aiogram long polling for dry_run Telegram commands."""

    resolved_settings = settings or load_settings()
    if not resolved_settings.telegram_enabled:
        return False
    if not resolved_settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required when TELEGRAM_ENABLED=true.")

    resolved_storage = storage
    if resolved_storage is None:
        from bot.storage.storage import SQLiteStorage

        resolved_storage = SQLiteStorage(resolved_settings.sqlite_db_path)

    await resolved_storage.init_db()
    resolved_state_provider = state_provider or build_storage_backed_state_provider(
        settings=resolved_settings,
        storage=resolved_storage,
    )
    resolved_controller = controller or build_telegram_controller(
        settings=resolved_settings,
        storage=resolved_storage,
        state_provider=resolved_state_provider,
    )
    resolved_dispatcher = dispatcher or build_telegram_dispatcher(resolved_controller)

    owns_bot = bot is None
    resolved_bot = bot or Bot(token=resolved_settings.telegram_bot_token)
    try:
        await resolved_dispatcher.start_polling(resolved_bot)
    finally:
        if owns_bot:
            await resolved_bot.session.close()
    return True


async def _run_handler(
    message: Message,
    controller: TelegramBotController,
    handler: Callable[[Message, TelegramBotController], Awaitable[None]],
) -> None:
    """Execute one command handler and return a friendly error message on failure."""

    try:
        await handler(message, controller)
    except Exception:
        await message.answer("Telegram command failed. Please try again.")


def _chat_id(message: Message) -> int:
    return int(message.chat.id)


def _username(message: Message) -> str | None:
    return message.from_user.username if message.from_user is not None else None


def _first_name(message: Message) -> str | None:
    return message.from_user.first_name if message.from_user is not None else None


async def _async_main() -> None:
    await run_telegram_polling()


def main() -> None:
    """Run Telegram long polling for dry_run commands."""

    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
