from __future__ import annotations

import asyncio

import mongomock

from src.infrastructure.sales_monitoring.mongo_worker_status import (
    MongoSalesMonitoringWorkerStatusRepository,
)
from src.infrastructure.sales_monitoring.worker_runtime import SalesMonitoringWorkerRuntime

_HEARTBEAT = "2026-07-29T08:00:00+00:00"


class _Status:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))


class _Scheduler:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _Clock:
    def __init__(self) -> None:
        self._n = 0

    def now_utc_iso(self) -> str:
        self._n += 1
        return f"2026-07-29T00:00:0{self._n}Z"


async def _run_until_shutdown(
    runtime: SalesMonitoringWorkerRuntime,
    status: _Status,
    *,
    heartbeats: int,
) -> None:
    task = asyncio.create_task(runtime.run())
    while len(status.heartbeats) < heartbeats:
        await asyncio.sleep(0)
    runtime.request_shutdown()
    await task


def test_disabled_worker_heartbeats_without_scheduler() -> None:
    status = _Status()
    scheduler = _Scheduler()
    runtime = SalesMonitoringWorkerRuntime(
        enabled=False,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=60.0,
    )
    asyncio.run(_run_until_shutdown(runtime, status, heartbeats=1))

    assert scheduler.started is False
    assert scheduler.stopped is True
    assert status.heartbeats == [("2026-07-29T00:00:01Z", False)]


def test_heartbeat_writes_worker_status_document() -> None:
    collection = mongomock.MongoClient().db.sales_monitoring_worker_status
    repository = MongoSalesMonitoringWorkerStatusRepository(collection)

    repository.record_heartbeat(at=_HEARTBEAT, enabled=True)

    assert collection.find_one({"_id": "worker"}) == {
        "_id": "worker",
        "last_heartbeat_at": _HEARTBEAT,
        "worker_enabled": True,
    }

    repository.record_heartbeat(at="2026-07-29T08:01:00+00:00", enabled=False)

    assert collection.count_documents({}) == 1
    document = collection.find_one({"_id": "worker"})
    assert document is not None
    assert document["last_heartbeat_at"] == "2026-07-29T08:01:00+00:00"
    assert document["worker_enabled"] is False


class _FlakyStatus:
    def __init__(self) -> None:
        self.calls = 0
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("mongo blip")
        self.heartbeats.append((at, enabled))


def test_sales_monitoring_worker_heartbeat_failure_continues_loop() -> None:
    status = _FlakyStatus()
    runtime = SalesMonitoringWorkerRuntime(
        enabled=False,
        status_repository=status,
        scheduler=_Scheduler(),
        clock=_Clock(),
        heartbeat_interval_seconds=0.01,
    )

    async def _run() -> None:
        task = asyncio.create_task(runtime.run())
        while len(status.heartbeats) < 1:
            await asyncio.sleep(0)
        runtime.request_shutdown()
        await task

    asyncio.run(_run())
    assert len(status.heartbeats) >= 1
