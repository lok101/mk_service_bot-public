from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from src.application.product_identity.sync_procurement_mirror import (
    ProcurementMirrorSyncStats,
)
from src.infrastructure.product_identity.procurement_mirror_worker import (
    ProductProcurementMirrorSyncWorker,
)


class _FakeSync:
    def __init__(self) -> None:
        self.calls = 0
        self.thread_ids: list[int] = []

    def sync_all(self) -> ProcurementMirrorSyncStats:
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        return ProcurementMirrorSyncStats(
            requested=0,
            upserted=0,
            empty_supply=0,
            http_failed=0,
            pruned=0,
        )


def test_procurement_mirror_worker_run_once_calls_sync_all() -> None:
    sync = _FakeSync()
    worker = ProductProcurementMirrorSyncWorker(sync=sync, interval_seconds=60)
    asyncio.run(worker.run_once())
    assert sync.calls == 1


def test_procurement_mirror_worker_run_once_offloads_sync_to_thread() -> None:
    sync = _FakeSync()
    worker = ProductProcurementMirrorSyncWorker(sync=sync, interval_seconds=60)

    async def _scenario() -> None:
        main_ident = threading.get_ident()
        await worker.run_once()
        assert sync.calls == 1
        assert sync.thread_ids == [sync.thread_ids[0]]
        assert sync.thread_ids[0] != main_ident

    asyncio.run(_scenario())


def test_procurement_mirror_worker_run_continues_after_tick_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sync = _FakeSync()
    worker = ProductProcurementMirrorSyncWorker(sync=sync, interval_seconds=0)
    stop = asyncio.Event()
    ticks = {"n": 0}

    async def flaky_run_once(self: ProductProcurementMirrorSyncWorker) -> None:
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise ConnectionError("mongo blip")
        self.sync.sync_all()
        stop.set()

    monkeypatch.setattr(ProductProcurementMirrorSyncWorker, "run_once", flaky_run_once)

    async def _scenario() -> None:
        await asyncio.wait_for(worker.run(stop), timeout=2.0)

    with caplog.at_level(logging.ERROR):
        asyncio.run(_scenario())

    assert ticks["n"] >= 2
    assert sync.calls == 1
    assert any(
        record.message == "product_procurement_mirror_sync_tick_failed" for record in caplog.records
    )
