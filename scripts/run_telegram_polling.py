"""Local production-like launcher for Telegram long polling in dry_run v1."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Awaitable, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from bot.app import (
    APP_RUNTIME_TELEGRAM_ONLY,
    AppContext,
    AppLaunchError,
    build_telegram_polling_context,
    validate_telegram_runtime,
)
from bot.config import Settings, load_settings


BuildContext = Callable[..., Awaitable[AppContext]]


async def run_telegram_polling_script(
    *,
    settings: Settings | None = None,
    build_context: BuildContext | None = None,
) -> int:
    """Build Telegram-only runtime context and start aiogram long polling."""

    resolved_settings = settings or load_settings(PROJECT_ROOT / ".env")
    print(f"mode: {resolved_settings.mode.value}")
    print(f"app_runtime_mode: {APP_RUNTIME_TELEGRAM_ONLY}")
    print(f"telegram_enabled: {resolved_settings.telegram_enabled}")
    print(f"bot_token_configured: {'yes' if bool(resolved_settings.telegram_bot_token) else 'no'}")
    print("state_source: storage snapshot")

    try:
        validate_telegram_runtime(
            settings=resolved_settings,
            app_runtime_mode=APP_RUNTIME_TELEGRAM_ONLY,
        )
        context_builder = build_context or build_telegram_polling_context
        context = await context_builder(settings=resolved_settings)
        telegram_service = context.telegram_service
        if telegram_service is None or telegram_service.polling_runner is None:
            raise AppLaunchError("Telegram polling service is not available.")

        print("telegram polling starting...")
        print("manual_checklist:")
        print("1. Open Telegram and find the bot.")
        print("2. Send /start.")
        print("3. Send /status.")
        print("4. Send /position.")
        print("5. Send /pnl.")
        print("6. Send /sync.")
        print("7. Send /stop.")

        await telegram_service.polling_runner()
        return 0
    except AppLaunchError as exc:
        print(f"Telegram polling launcher error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected Telegram polling error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    """Run the local Telegram long-polling launcher and exit with an explicit status code."""

    raise SystemExit(asyncio.run(run_telegram_polling_script()))


if __name__ == "__main__":
    main()
