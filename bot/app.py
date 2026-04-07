"""Application/runtime composition layer for dry_run and Telegram services."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

from bot.config import Settings, load_settings
from bot.main import (
    BootstrapMarketSourceProtocol,
    BootstrapStorageProtocol,
    DryRunStack,
    build_dry_run_stack,
)


APP_RUNTIME_DRY_RUN_ONLY = "dry_run_only"
APP_RUNTIME_TELEGRAM_ONLY = "telegram_only"
APP_RUNTIME_DRY_RUN_WITH_TELEGRAM = "dry_run_with_telegram"
VALID_APP_RUNTIME_MODES = {
    APP_RUNTIME_DRY_RUN_ONLY,
    APP_RUNTIME_TELEGRAM_ONLY,
    APP_RUNTIME_DRY_RUN_WITH_TELEGRAM,
}


class AppLaunchError(RuntimeError):
    """Raised when the runtime composition layer cannot start the requested services."""


StateProvider = Callable[[], object]
PollingRunner = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class DryRunService:
    """Warmed-up dry_run service wrapper."""

    stack: DryRunStack
    readiness_message: str


@dataclass(slots=True)
class TelegramService:
    """Telegram polling service wrapper."""

    enabled: bool
    state_provider: StateProvider | None
    controller: object | None
    polling_runner: PollingRunner | None


@dataclass(slots=True)
class AppContext:
    """Composed runtime context for one launcher mode."""

    settings: Settings
    storage: BootstrapStorageProtocol
    app_runtime_mode: str
    dry_run_service: DryRunService | None = None
    telegram_service: TelegramService | None = None


async def build_dry_run_service(
    *,
    settings: Settings,
    storage: BootstrapStorageProtocol | None = None,
    market_source: BootstrapMarketSourceProtocol | None = None,
) -> DryRunService:
    """Build a warmed-up dry_run service without starting any continuous market loop."""

    stack = await build_dry_run_stack(
        settings=settings,
        storage=storage,
        market_source=market_source,
    )
    readiness_message = (
        f"dry_run ready: {stack.settings.symbol} {stack.settings.timeframe} "
        f"startup_candles_loaded={stack.startup_candles_loaded} "
        f"last_candle_time={stack.runtime_state.last_candle_time.isoformat() if stack.runtime_state.last_candle_time else 'none'}"
    )
    return DryRunService(stack=stack, readiness_message=readiness_message)


async def build_telegram_service(
    *,
    settings: Settings,
    storage: BootstrapStorageProtocol,
    runtime_state_getter: Callable[[], object | None] | None = None,
    state_provider_builder: Callable[..., StateProvider] | None = None,
    controller_builder: Callable[..., object] | None = None,
    polling_runner_builder: Callable[..., PollingRunner] | None = None,
) -> TelegramService:
    """Build the Telegram polling service wrapper without starting polling automatically."""

    await storage.init_db()

    if not settings.telegram_enabled:
        return TelegramService(
            enabled=False,
            state_provider=None,
            controller=None,
            polling_runner=None,
        )

    if not settings.telegram_bot_token:
        raise AppLaunchError("TELEGRAM_BOT_TOKEN is required when Telegram runtime is enabled.")

    if state_provider_builder is None or controller_builder is None or polling_runner_builder is None:
        from bot.telegram.telegram_runner import (
            build_storage_backed_state_provider,
            build_telegram_controller,
            run_telegram_polling,
        )

        state_provider_builder = state_provider_builder or build_storage_backed_state_provider
        controller_builder = controller_builder or build_telegram_controller

        def _default_polling_runner_builder(*, settings: Settings, storage: BootstrapStorageProtocol, state_provider, controller) -> PollingRunner:
            async def _runner() -> bool:
                return await run_telegram_polling(
                    settings=settings,
                    storage=storage,
                    state_provider=state_provider,
                    controller=controller,
                )

            return _runner

        polling_runner_builder = polling_runner_builder or _default_polling_runner_builder

    state_provider = state_provider_builder(
        settings=settings,
        storage=storage,
        runtime_state_getter=runtime_state_getter,
    )
    controller = controller_builder(
        settings=settings,
        storage=storage,
        state_provider=state_provider,
    )
    polling_runner = polling_runner_builder(
        settings=settings,
        storage=storage,
        state_provider=state_provider,
        controller=controller,
    )
    return TelegramService(
        enabled=True,
        state_provider=state_provider,
        controller=controller,
        polling_runner=polling_runner,
    )


async def build_app_context(
    *,
    settings: Settings | None = None,
    app_runtime_mode: str | None = None,
    storage: BootstrapStorageProtocol | None = None,
    market_source: BootstrapMarketSourceProtocol | None = None,
    state_provider_builder: Callable[..., StateProvider] | None = None,
    controller_builder: Callable[..., object] | None = None,
    polling_runner_builder: Callable[..., PollingRunner] | None = None,
) -> AppContext:
    """Compose the requested runtime services without embedding trading logic."""

    resolved_settings = settings or load_settings()
    resolved_runtime_mode = resolve_app_runtime_mode(app_runtime_mode=app_runtime_mode)

    resolved_storage = storage
    if resolved_storage is None:
        from bot.storage.storage import SQLiteStorage

        resolved_storage = SQLiteStorage(resolved_settings.sqlite_db_path)

    dry_run_service: DryRunService | None = None
    if resolved_runtime_mode in {APP_RUNTIME_DRY_RUN_ONLY, APP_RUNTIME_DRY_RUN_WITH_TELEGRAM}:
        dry_run_service = await build_dry_run_service(
            settings=resolved_settings,
            storage=resolved_storage,
            market_source=market_source,
        )

    telegram_service: TelegramService | None = None
    if resolved_runtime_mode in {APP_RUNTIME_TELEGRAM_ONLY, APP_RUNTIME_DRY_RUN_WITH_TELEGRAM}:
        runtime_state_getter = None
        if dry_run_service is not None:
            runtime_state_getter = lambda: dry_run_service.stack.orchestrator.runtime_state

        telegram_service = await build_telegram_service(
            settings=resolved_settings,
            storage=resolved_storage,
            runtime_state_getter=runtime_state_getter,
            state_provider_builder=state_provider_builder,
            controller_builder=controller_builder,
            polling_runner_builder=polling_runner_builder,
        )

    return AppContext(
        settings=resolved_settings,
        storage=resolved_storage,
        app_runtime_mode=resolved_runtime_mode,
        dry_run_service=dry_run_service,
        telegram_service=telegram_service,
    )


async def run_dry_run_only(**kwargs) -> AppContext:
    """Build only the warmed-up dry_run service and return its context."""

    return await build_app_context(app_runtime_mode=APP_RUNTIME_DRY_RUN_ONLY, **kwargs)


async def run_telegram_only(**kwargs) -> AppContext:
    """Build Telegram-only runtime and start polling if enabled."""

    context = await build_app_context(app_runtime_mode=APP_RUNTIME_TELEGRAM_ONLY, **kwargs)
    telegram_service = context.telegram_service
    if telegram_service is None:
        raise AppLaunchError("Telegram service was not built for telegram_only mode.")
    if not telegram_service.enabled:
        raise AppLaunchError("APP_RUNTIME_MODE=telegram_only requires TELEGRAM_ENABLED=true.")
    if telegram_service.polling_runner is None:
        raise AppLaunchError("Telegram polling runner is not configured.")
    await telegram_service.polling_runner()
    return context


async def run_dry_run_with_telegram(**kwargs) -> AppContext:
    """Build warmed-up dry_run context and start Telegram polling as the active runtime component."""

    context = await build_app_context(app_runtime_mode=APP_RUNTIME_DRY_RUN_WITH_TELEGRAM, **kwargs)
    telegram_service = context.telegram_service
    if telegram_service is None:
        raise AppLaunchError("Telegram service was not built for dry_run_with_telegram mode.")
    if not telegram_service.enabled:
        raise AppLaunchError("APP_RUNTIME_MODE=dry_run_with_telegram requires TELEGRAM_ENABLED=true.")
    if telegram_service.polling_runner is None:
        raise AppLaunchError("Telegram polling runner is not configured.")
    await telegram_service.polling_runner()
    return context


def resolve_app_runtime_mode(*, app_runtime_mode: str | None = None, environ: dict[str, str] | None = None) -> str:
    """Resolve the launcher/runtime composition mode from argument or environment."""

    if app_runtime_mode is not None:
        candidate = app_runtime_mode
    else:
        env = environ or os.environ
        candidate = env.get("APP_RUNTIME_MODE", APP_RUNTIME_DRY_RUN_ONLY)

    if candidate not in VALID_APP_RUNTIME_MODES:
        allowed = ", ".join(sorted(VALID_APP_RUNTIME_MODES))
        raise AppLaunchError(f"Unsupported APP_RUNTIME_MODE='{candidate}'. Allowed values: {allowed}")
    return candidate


async def _async_main() -> None:
    """Run one runtime mode resolved from APP_RUNTIME_MODE."""

    runtime_mode = resolve_app_runtime_mode()
    if runtime_mode == APP_RUNTIME_DRY_RUN_ONLY:
        context = await run_dry_run_only()
        if context.dry_run_service is not None:
            print(context.dry_run_service.readiness_message)
        return
    if runtime_mode == APP_RUNTIME_TELEGRAM_ONLY:
        await run_telegram_only()
        return
    if runtime_mode == APP_RUNTIME_DRY_RUN_WITH_TELEGRAM:
        await run_dry_run_with_telegram()
        return
    raise AppLaunchError(f"Unhandled APP_RUNTIME_MODE='{runtime_mode}'")


def main() -> None:
    """Thin application entrypoint for runtime/service composition."""

    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
