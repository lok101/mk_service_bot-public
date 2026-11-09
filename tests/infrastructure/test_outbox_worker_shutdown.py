from __future__ import annotations

import asyncio

from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.worker import OutboxWorker


def test_outbox_worker_stops_when_shutdown_requested() -> None:
    asyncio.run(_test_outbox_worker_stops_when_shutdown_requested())


async def _test_outbox_worker_stops_when_shutdown_requested() -> None:
    worker = OutboxWorker(
        store=InMemoryOutboxStore(),
        processors=OutboxProcessorRegistry(),
        poll_interval_seconds=0.01,
    )
    shutdown = asyncio.Event()

    async def run_until_shutdown() -> None:
        await worker.run_until_shutdown(shutdown)

    task = asyncio.create_task(run_until_shutdown())
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(task, timeout=1.0)
