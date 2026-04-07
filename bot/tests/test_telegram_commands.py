"""Tests for Telegram commands, formatting, and fail-safe notifier behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from bot.config import BotMode, EvenBarAnchorMode, Settings
from bot.data.candle_clock import CandleClock
from bot.data.market_stream import Candle, CandleUpdateBuffer
from bot.engine.position_manager import PositionManager
from bot.engine.risk_manager import RiskManager
from bot.engine.strategy_engine import StrategyEngine
from bot.execution.dry_run_executor import DryRunExecutor
from bot.execution.order_manager import OrderManager
from bot.runner.orchestrator import DryRunOrchestrator
from bot.storage.models import BotState, EventRecord, EventType, InstrumentConstraints, SafeStopRecord, SubscriberRecord
from bot.telegram.telegram_bot import TelegramBotController
from bot.telegram.telegram_notifier import TelegramNotifier
from bot.utils.rounding import OrderNormalizer


@dataclass
class InMemoryTelegramStorage:
    """Minimal storage used for Telegram and orchestrator tests."""

    state: BotState
    subscribers: dict[int, SubscriberRecord] = field(default_factory=dict)
    saved_events: list[EventRecord] = field(default_factory=list)
    saved_orders: list[object] = field(default_factory=list)
    saved_fills: list[object] = field(default_factory=list)
    safe_stops: list[SafeStopRecord] = field(default_factory=list)

    async def add_subscriber(self, subscriber: SubscriberRecord) -> None:
        self.subscribers[subscriber.chat_id] = subscriber

    async def deactivate_subscriber(self, chat_id: int) -> None:
        existing = self.subscribers.get(chat_id)
        if existing is not None:
            existing.is_active = False

    async def list_active_subscribers(self) -> list[SubscriberRecord]:
        return [item for item in self.subscribers.values() if item.is_active]

    async def save_bot_state(self, state: BotState) -> None:
        self.state = state

    async def save_order(self, order) -> None:
        self.saved_orders.append(order)

    async def save_fill(self, fill) -> None:
        self.saved_fills.append(fill)

    async def save_event(self, event: EventRecord) -> None:
        self.saved_events.append(event)

    async def save_safe_stop_reason(self, record: SafeStopRecord) -> None:
        self.safe_stops.append(record)


def _state() -> BotState:
    return BotState(
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        last_candle_time=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
        pos_size_abs=0.09,
        avg_price=68000.0,
        num_sells=1,
        trailing_active=False,
        last_fill_price=68010.0,
    )


def _constraints() -> InstrumentConstraints:
    return InstrumentConstraints(
        symbol="BTC-USDT",
        tick_size=0.1,
        lot_step=0.0001,
        min_qty=0.0001,
        min_notional=2.0,
        price_precision=1,
        qty_precision=4,
    )


def _event(event_type: EventType, *, reason: str | None = None) -> EventRecord:
    return EventRecord(
        event_id=f"{event_type.value}:1",
        event_type=event_type,
        mode=BotMode.DRY_RUN,
        symbol="BTC-USDT",
        timeframe="1m",
        reason=reason,
        created_at=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
        price=68000.0,
        qty=0.09,
        position_size=0.09,
        avg_price=68000.0,
        cycle_id=1,
    )


def _controller(storage: InMemoryTelegramStorage, notifier: TelegramNotifier | None = None) -> TelegramBotController:
    notifier = notifier or TelegramNotifier(storage=storage, bot_token=None, enabled=False)
    return TelegramBotController(notifier=notifier, state_getter=lambda: storage.state)


@pytest.mark.asyncio
async def test_start_adds_subscriber() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    controller = _controller(storage, notifier=TelegramNotifier(storage=storage, bot_token=None, enabled=False))

    text = await controller.handle_start(123, "alice", "Alice")

    assert "Subscription enabled" in text
    assert 123 in storage.subscribers
    assert storage.subscribers[123].is_active is True


@pytest.mark.asyncio
async def test_stop_deactivates_subscriber() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    storage.subscribers[123] = SubscriberRecord(
        chat_id=123,
        username="alice",
        first_name="Alice",
        created_at=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
        is_active=True,
    )
    controller = _controller(storage, notifier=TelegramNotifier(storage=storage, bot_token=None, enabled=False))

    text = await controller.handle_stop(123)

    assert "Subscription disabled" in text
    assert storage.subscribers[123].is_active is False


@pytest.mark.asyncio
async def test_status_reads_local_runtime_state() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    controller = _controller(storage)

    text = await controller.handle_status(123)

    assert "mode: dry_run" in text
    assert "symbol: BTC-USDT" in text
    assert "last_candle_time:" in text
    assert "safe_stop_active: False" in text


@pytest.mark.asyncio
async def test_position_reads_local_runtime_state() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    controller = _controller(storage)

    text = await controller.handle_position(123)

    assert "pos_size_abs: 0.09" in text
    assert "avg_price: 68000.0" in text
    assert "num_sells: 1" in text


@pytest.mark.asyncio
async def test_pnl_returns_limited_dry_run_summary() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    controller = _controller(storage)

    text = await controller.handle_pnl(123)

    assert "PnL summary not fully implemented yet" in text
    assert "last_fill_price:" in text


@pytest.mark.asyncio
async def test_sync_returns_stub_without_exchange_access() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    controller = _controller(storage)

    text = await controller.handle_sync(123)

    assert text == "sync not implemented in dry_run v1"


@pytest.mark.asyncio
async def test_notifier_broadcast_reads_active_subscribers() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    storage.subscribers[1] = SubscriberRecord(1, "a", "A", datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc), True)
    storage.subscribers[2] = SubscriberRecord(2, "b", "B", datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc), False)
    sent: list[tuple[int, str]] = []

    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    notifier = TelegramNotifier(storage=storage, bot_token="token", sender=sender, max_messages_per_second=100)

    delivered = await notifier.broadcast("hello")

    assert delivered == 1
    assert sent == [(1, "hello")]


@pytest.mark.asyncio
async def test_dry_run_execution_event_can_be_formatted_and_sent() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    storage.subscribers[1] = SubscriberRecord(1, "a", "A", datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc), True)
    sent: list[tuple[int, str]] = []

    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    notifier = TelegramNotifier(storage=storage, bot_token="token", sender=sender, max_messages_per_second=100)

    delivered = await notifier.broadcast_event(_event(EventType.FIRST_SHORT, reason="first_short"))

    assert delivered == 1
    assert sent
    assert "FIRST_SHORT" in sent[0][1]


@pytest.mark.asyncio
async def test_telegram_failure_does_not_break_notifier() -> None:
    storage = InMemoryTelegramStorage(state=_state())
    storage.subscribers[1] = SubscriberRecord(1, "a", "A", datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc), True)

    async def sender(chat_id: int, text: str) -> None:
        raise RuntimeError("telegram down")

    notifier = TelegramNotifier(storage=storage, bot_token="token", sender=sender, max_messages_per_second=100)

    delivered = await notifier.broadcast("hello")

    assert delivered == 0


def test_safe_stop_event_is_formatted_for_telegram() -> None:
    text = TelegramNotifier.format_event_message(_event(EventType.SAFE_STOP, reason="manual safe stop"))

    assert "[DRY_RUN] SAFE_STOP" in text
    assert "BTC-USDT 1m" in text
    assert "status: SAFE_STOP" in text
    assert "reason: manual safe stop" in text


def test_dry_run_execution_event_is_formatted_for_telegram() -> None:
    text = TelegramNotifier.format_event_message(_event(EventType.FIRST_SHORT, reason="first_short"))

    assert "[DRY_RUN] FIRST_SHORT" in text
    assert "price: 68000.0" in text
    assert "qty: 0.09" in text
    assert "cycle_id: 1" in text


@pytest.mark.asyncio
async def test_orchestrator_pipeline_survives_notifier_failure() -> None:
    storage = InMemoryTelegramStorage(state=BotState(mode=BotMode.DRY_RUN, symbol="BTC-USDT", timeframe="1m"))

    class ExplodingNotifier:
        async def broadcast_event(self, event: EventRecord) -> int:
            raise RuntimeError("telegram send failed")

    orchestrator = DryRunOrchestrator(
        symbol="BTC-USDT",
        timeframe="1m",
        runtime_state=storage.state,
        storage=storage,
        candle_buffer=CandleUpdateBuffer(),
        candle_clock=CandleClock(
            timeframe="1m",
            anchor_mode=EvenBarAnchorMode.FIXED_TIMESTAMP,
            fixed_timestamp=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
        ),
        strategy_engine=StrategyEngine(),
        executor=DryRunExecutor(
            risk_manager=RiskManager(Settings()),
            order_manager=OrderManager(),
            position_manager=PositionManager(),
            order_normalizer=OrderNormalizer(Settings().invalid_order_policy),
        ),
        constraints=_constraints(),
        notifier=ExplodingNotifier(),
    )

    await orchestrator.process_candle_update(
        Candle(
            open_time=datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc),
            close_time=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
            open=67990.0,
            high=68010.0,
            low=67980.0,
            close=68000.0,
            volume=1.0,
        )
    )
    result = await orchestrator.process_candle_update(
        Candle(
            open_time=datetime(2026, 4, 11, 12, 1, tzinfo=timezone.utc),
            close_time=datetime(2026, 4, 11, 12, 2, tzinfo=timezone.utc),
            open=68000.0,
            high=68020.0,
            low=67990.0,
            close=68010.0,
            volume=1.0,
        )
    )

    assert result.closed_bar_processed is True
    assert storage.saved_orders or result.execution_results == []
