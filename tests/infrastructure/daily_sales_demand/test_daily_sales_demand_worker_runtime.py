from __future__ import annotations

import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import mongomock

from src.application.outbox import DAILY_SALES_DEMAND_HANDLER_ID
from src.infrastructure.daily_sales_demand.cron_scheduler import DailySalesDemandCronScheduler
from src.infrastructure.daily_sales_demand.cron_tick import run_daily_sales_demand_tick
from src.infrastructure.daily_sales_demand.mongo_worker_status import (
    MongoDailySalesDemandWorkerStatusRepository,
)
from src.infrastructure.daily_sales_demand.worker_runtime import DailySalesDemandWorkerRuntime
from src.infrastructure.outbox.memory import InMemoryOutboxStore


class _FakeDrainer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._remaining = 2

    def drain_handler(self, handler_id: str) -> int:
        self.calls.append(handler_id)
        if self._remaining <= 0:
            return 0
        self._remaining -= 1
        return 1


class _CapturingBackend:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, object]] = []
        self.started = False
        self.stopped = False

    def add_cron_job(
        self,
        *,
        crontab: str,
        timezone: object,
        callback: object,
        job_id: str,
        max_instances: int = 1,
    ) -> None:
        del timezone, max_instances
        self.jobs.append((crontab, job_id, callback))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_targeted_drain_daily_sales_demand() -> None:
    store = InMemoryOutboxStore(max_attempts=5)
    drainer = _FakeDrainer()
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 8, 10, 4, 0, tzinfo=tz)

    run_daily_sales_demand_tick(
        outbox=store,
        drainer=drainer,
        now=now,
        tz=tz,
    )

    entries = list(store._entries.values())
    assert len(entries) == 1
    assert entries[0]["event_id"] == "daily_sales_demand:2026-08-09"
    assert entries[0]["handler_id"] == DAILY_SALES_DEMAND_HANDLER_ID
    assert drainer.calls == [
        DAILY_SALES_DEMAND_HANDLER_ID,
        DAILY_SALES_DEMAND_HANDLER_ID,
        DAILY_SALES_DEMAND_HANDLER_ID,
    ]


def test_cron_scheduler_registers_hour_crontab() -> None:
    backend = _CapturingBackend()
    tz = ZoneInfo("Europe/Moscow")
    ticks: list[date] = []

    def callback() -> None:
        ticks.append(date(2026, 8, 9))

    scheduler = DailySalesDemandCronScheduler(
        enabled=True,
        cron_hour=4,
        timezone=tz,
        callback=callback,
        backend=backend,
    )
    scheduler.start()

    assert backend.started is True
    assert len(backend.jobs) == 1
    crontab, job_id, job_callback = backend.jobs[0]
    assert crontab == "0 4 * * *"
    assert job_id == "daily_sales_demand_enqueue"
    job_callback()
    assert ticks == [date(2026, 8, 9)]

    scheduler.stop()
    assert backend.stopped is True


def test_disabled_cron_scheduler_does_not_start_backend() -> None:
    backend = _CapturingBackend()
    scheduler = DailySalesDemandCronScheduler(
        enabled=False,
        cron_hour=4,
        timezone=ZoneInfo("Europe/Moscow"),
        callback=lambda: None,
        backend=backend,
    )
    scheduler.start()
    assert backend.started is False
    assert backend.jobs == []


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
        return f"2026-08-10T00:00:0{self._n}Z"


async def _run_until_shutdown(
    runtime: DailySalesDemandWorkerRuntime,
    status: _Status,
    *,
    heartbeats: int,
) -> None:
    task = asyncio.create_task(runtime.run())
    while len(status.heartbeats) < heartbeats:
        await asyncio.sleep(0)
    runtime.request_shutdown()
    await task


def test_disabled_worker_idles_without_cron() -> None:
    status = _Status()
    scheduler = _Scheduler()
    runtime = DailySalesDemandWorkerRuntime(
        enabled=False,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=60.0,
    )
    asyncio.run(_run_until_shutdown(runtime, status, heartbeats=1))

    assert scheduler.started is False
    assert scheduler.stopped is True
    assert status.heartbeats == [("2026-08-10T00:00:01Z", False)]


def test_heartbeat_writes_worker_status_document() -> None:
    collection = mongomock.MongoClient().db.daily_sales_demand_worker_status
    repository = MongoDailySalesDemandWorkerStatusRepository(collection)
    at = "2026-08-10T04:00:00+00:00"

    repository.record_heartbeat(at=at, enabled=True)

    assert collection.find_one({"_id": "worker"}) == {
        "_id": "worker",
        "last_heartbeat_at": at,
        "worker_enabled": True,
    }


class _FlakyStatus:
    def __init__(self) -> None:
        self.calls = 0
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("mongo blip")
        self.heartbeats.append((at, enabled))


def test_daily_sales_demand_worker_heartbeat_failure_continues_loop() -> None:
    status = _FlakyStatus()
    runtime = DailySalesDemandWorkerRuntime(
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
