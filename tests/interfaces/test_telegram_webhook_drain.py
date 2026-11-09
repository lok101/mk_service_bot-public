from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from src.interfaces.telegram import webhook_api
from src.interfaces.telegram.webhook_api import drain_telegram_background_tasks


@pytest.fixture(autouse=True)
def _clear_background_tasks() -> None:
    webhook_api._BACKGROUND_TASKS.clear()
    yield
    webhook_api._BACKGROUND_TASKS.clear()


def test_drain_telegram_background_tasks_waits_for_completion() -> None:
    asyncio.run(_test_drain_telegram_background_tasks_waits_for_completion())


async def _test_drain_telegram_background_tasks_waits_for_completion() -> None:
    completed = False

    async def quick_task() -> None:
        nonlocal completed
        await asyncio.sleep(0.02)
        completed = True

    task = asyncio.create_task(quick_task())
    webhook_api._BACKGROUND_TASKS.add(task)
    task.add_done_callback(webhook_api._BACKGROUND_TASKS.discard)

    await drain_telegram_background_tasks(timeout_seconds=1.0)

    assert completed
    assert task.done()


def test_drain_telegram_background_tasks_logs_pending_on_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_test_drain_telegram_background_tasks_logs_pending_on_timeout(caplog))


async def _test_drain_telegram_background_tasks_logs_pending_on_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    async def slow_task() -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(slow_task())
    webhook_api._BACKGROUND_TASKS.add(task)
    try:
        await drain_telegram_background_tasks(timeout_seconds=0.01)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert any("still running" in record.message for record in caplog.records)
