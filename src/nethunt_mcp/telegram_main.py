from __future__ import annotations

import asyncio
import os

from .config import DEFAULT_LOG_LEVEL, TelegramBotSettings, load_runtime_env
from .errors import ConfigError
from .server import configure_logging
from .telegram_bot import TelegramBotApp


async def _run_bot() -> None:
    load_runtime_env()
    configure_logging(os.environ.get("NETHUNT_LOG_LEVEL", DEFAULT_LOG_LEVEL))
    settings = TelegramBotSettings.from_env()
    app = TelegramBotApp(settings)
    await app.run()


def main() -> None:
    try:
        asyncio.run(_run_bot())
    except ConfigError as exc:
        raise SystemExit(exc.message) from exc
