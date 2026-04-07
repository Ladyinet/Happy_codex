"""Tests for the aiogram dry_run Telegram polling runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, Settings
from bot.storage.models import BotState, SubscriberRecord
from bot.telegram.telegram_runner import (
    build_storage_backed_state_provider,
    build_telegram_controller,
    build_telegram_dispatcher,
    build_telegram_router,
    handle_pnl_command,
    handle_position_command,
    handle_start_command,
    handle_status_command,
    handle_stop_command,
    handle_sync_command,
    run_telegram_polling,
    _run_handler,
)


@dataclass
class FakeStorage:
    """Minimal storage used by Telegram runner tests."""

    state: BotState | None = None
    subscribers: dict[int, SubscriberRecord] = field(default_factory=dict)
    init_db_calls: int = 0

    async def init_db(self) -> None:
        self.init_db_calls += 1

    async def load_bot_state(self, mode, symbol: str, timeframe: str) -> BotState | None:
        return self.state

    async def add_subscriber(self, subscriber: SubscriberRecord) -> None:
        self.subscribers[subscriber.chat_id] = subscriber

    async def deactivate_subscriber(self, chat_id: int) -> None:
        if chat_id in self.subscribers:
            self.subscribers[chat_id].is_active = False

    async def list_active_subscribers(self):
        return [item for item in self.subscribers.values() if item.is_active]


@dataclass
class FakeUser:
    """Simple Telegram user stub."""

    id: int
    username: str | None = None
    first_name: str | None = None


@dataclass
class FakeChat:
    """Simple Telegram chat stub."""

    id: int


@dataclass
class FakeMessage:
    """Simple aiogram-like message stub for handler tests."""

    chat: FakeChat
    from_user: FakeUser | None = None
    answers: list[str] = field(default_factory=list)

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class FakeDispatcher:
    """Fake dispatcher for polling-runner tests."""

    def __init__(self) -> None:
        self.start_polling_calls = 0
        self.last_bot = None

    async def start_polling(self, bot) -> None:
        self.start_polling_calls += 1
        self.last_bot = bot


class FakeSession:
    """Fake bot session used to verify close calls."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBot:
    """Fake aiogram Bot used by polling tests."""

    def __init__(self) -> None:
        self.session = FakeSession()


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        telegram_enabled=enabled,
        telegram_bot_token="test-token" if enabled else None,
    )


def _state() -> BotState:
    return BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        pos_size_abs=0.09,
        avg_price=68000.0,
        num_sells=1,
        last_candle_time=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
    )


def _message(chat_id: int = 1, username: str | None = "alice", first_name: str | None = "Alice") -> FakeMessage:
    return FakeMessage(chat=FakeChat(chat_id), from_user=FakeUser(chat_id, username, first_name))


@pytest.mark.asyncio
async def test_router_registers_all_commands() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )

    router = build_telegram_router(controller)

    assert len(router.message.handlers) == 6


@pytest.mark.asyncio
async def test_start_handler_adds_subscriber() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_start_command(message, controller)

    assert 1 in storage.subscribers
    assert "Subscription enabled" in message.answers[0]


@pytest.mark.asyncio
async def test_stop_handler_deactivates_subscriber() -> None:
    storage = FakeStorage(state=_state())
    storage.subscribers[1] = SubscriberRecord(
        chat_id=1,
        username="alice",
        first_name="Alice",
        created_at=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
        is_active=True,
    )
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_stop_command(message, controller)

    assert storage.subscribers[1].is_active is False
    assert "Subscription disabled" in message.answers[0]


@pytest.mark.asyncio
async def test_status_handler_returns_local_state_summary() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_status_command(message, controller)

    assert "mode: dry_run" in message.answers[0]
    assert "symbol: BTC-USDT" in message.answers[0]


@pytest.mark.asyncio
async def test_position_handler_returns_local_position_summary() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_position_command(message, controller)

    assert "pos_size_abs: 0.09" in message.answers[0]
    assert "avg_price: 68000.0" in message.answers[0]


@pytest.mark.asyncio
async def test_pnl_handler_does_not_fail() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_pnl_command(message, controller)

    assert "PnL summary not fully implemented yet" in message.answers[0]


@pytest.mark.asyncio
async def test_sync_handler_returns_stub() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )
    message = _message()

    await handle_sync_command(message, controller)

    assert message.answers[0] == "sync not implemented in dry_run v1"


@pytest.mark.asyncio
async def test_handler_errors_return_friendly_reply_without_crashing() -> None:
    class ExplodingController:
        async def handle_status(self, chat_id: int) -> str:
            raise RuntimeError("boom")

    message = _message()

    await _run_handler(message, ExplodingController(), handle_status_command)

    assert message.answers == ["Telegram command failed. Please try again."]


@pytest.mark.asyncio
async def test_dispatcher_build_does_not_require_bingx_dependencies() -> None:
    storage = FakeStorage(state=_state())
    controller = build_telegram_controller(
        settings=_settings(),
        storage=storage,
        state_provider=build_storage_backed_state_provider(settings=_settings(), storage=storage),
    )

    dispatcher = build_telegram_dispatcher(controller)

    assert dispatcher is not None


@pytest.mark.asyncio
async def test_polling_runner_does_not_change_trading_state_directly() -> None:
    storage = FakeStorage(state=_state())
    state_provider = build_storage_backed_state_provider(settings=_settings(), storage=storage)
    controller = build_telegram_controller(settings=_settings(), storage=storage, state_provider=state_provider)
    dispatcher = FakeDispatcher()
    bot = FakeBot()

    before = storage.state.pos_size_abs
    result = await run_telegram_polling(
        settings=_settings(),
        storage=storage,
        state_provider=state_provider,
        controller=controller,
        dispatcher=dispatcher,
        bot=bot,
    )

    assert result is True
    assert dispatcher.start_polling_calls == 1
    assert storage.state.pos_size_abs == before
    assert bot.session.closed is False


@pytest.mark.asyncio
async def test_runner_returns_false_when_telegram_disabled() -> None:
    storage = FakeStorage(state=_state())
    dispatcher = FakeDispatcher()
    bot = FakeBot()

    result = await run_telegram_polling(
        settings=_settings(enabled=False),
        storage=storage,
        dispatcher=dispatcher,
        bot=bot,
    )

    assert result is False
    assert dispatcher.start_polling_calls == 0
