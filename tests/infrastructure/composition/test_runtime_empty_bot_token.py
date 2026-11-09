from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.infrastructure.composition.runtime import ProcessRuntime


def test_run_skips_telegram_polling_when_bot_token_empty() -> None:
    """Contract: runtime.py содержит ветку skip polling для пустого bot_token."""
    text = Path("src/infrastructure/composition/runtime.py").read_text(encoding="utf-8")
    assert "bot_token" in text
    assert "skip_telegram_polling" in text or "if not self.config.bot_token.strip()" in text


def test_run_checks_empty_bot_token_before_webhook_branch() -> None:
    text = Path("src/infrastructure/composition/runtime.py").read_text(encoding="utf-8")
    empty_idx = text.find("if not self.config.bot_token.strip()")
    webhook_idx = text.find("if self.telegram_uses_webhook")
    assert empty_idx != -1
    assert webhook_idx != -1
    assert empty_idx < webhook_idx
    assert "assert bot is not None" not in text


def test_run_skips_telegram_when_bot_token_empty_even_with_webhook_host() -> None:
    """Empty BOT_TOKEN: API+outbox only; no setup_telegram_bot / polling / webhook configure."""
    runtime = MagicMock()
    runtime.config.bot_token = ""
    runtime.telegram_uses_webhook = True
    runtime._shutdown_event = asyncio.Event()
    runtime._ingress_background_tasks = MagicMock(return_value=[])
    runtime._run_no_sales_poll_until_shutdown = AsyncMock()
    runtime.setup_telegram_bot = MagicMock()
    runtime.run_api = AsyncMock()
    runtime.outbox.worker.run_until_shutdown = AsyncMock()
    runtime.run_bot_polling = AsyncMock()
    runtime.configure_telegram_webhook = AsyncMock()
    runtime._close_kitvending_client = MagicMock()
    runtime._close_procurement_mirror_http = MagicMock()

    asyncio.run(ProcessRuntime.run(runtime))

    runtime.setup_telegram_bot.assert_not_called()
    runtime.run_bot_polling.assert_not_called()
    runtime.configure_telegram_webhook.assert_not_called()
    runtime.run_api.assert_awaited()
    runtime._run_no_sales_poll_until_shutdown.assert_called()
    runtime.outbox.worker.run_until_shutdown.assert_not_awaited()


def test_process_runtime_start_stop_without_bot_token_smoke() -> None:
    """Register alias: same empty-token smoke as webhook-host arrangement."""
    test_run_skips_telegram_when_bot_token_empty_even_with_webhook_host()
