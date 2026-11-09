from __future__ import annotations

import asyncio

from src.application.matrix_automation.job_models import MatrixDeployJob
from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime


class _Status:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))

    def record_terminal_job(self, job: MatrixDeployJob) -> None:
        return None


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
        return f"2026-07-13T00:00:0{self._n}Z"


async def _run_until_shutdown(
    runtime: MatrixWorkerRuntime,
    status: _Status,
    *,
    heartbeats: int,
) -> None:
    task = asyncio.create_task(runtime.run())
    while len(status.heartbeats) < heartbeats:
        await asyncio.sleep(0)
    runtime.request_shutdown()
    await task


def test_disabled_runtime_records_heartbeat_and_never_starts_scheduler() -> None:
    status = _Status()
    scheduler = _Scheduler()
    runtime = MatrixWorkerRuntime(
        enabled=False,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=60.0,
    )
    asyncio.run(_run_until_shutdown(runtime, status, heartbeats=1))

    assert scheduler.started is False
    assert scheduler.stopped is True
    assert status.heartbeats == [("2026-07-13T00:00:01Z", False)]


def test_enabled_runtime_starts_scheduler_and_records_heartbeat_every_60_seconds() -> None:
    status = _Status()
    scheduler = _Scheduler()
    runtime = MatrixWorkerRuntime(
        enabled=True,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=0.01,
    )

    async def scenario() -> None:
        task = asyncio.create_task(runtime.run())
        while len(status.heartbeats) < 2:
            await asyncio.sleep(0)
        runtime.request_shutdown()
        await task

    asyncio.run(scenario())

    assert scheduler.started is True
    assert scheduler.stopped is True
    assert status.heartbeats == [
        ("2026-07-13T00:00:01Z", True),
        ("2026-07-13T00:00:02Z", True),
    ]


def test_runtime_stops_scheduler_on_shutdown() -> None:
    status = _Status()
    scheduler = _Scheduler()
    runtime = MatrixWorkerRuntime(
        enabled=True,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=60.0,
    )
    asyncio.run(_run_until_shutdown(runtime, status, heartbeats=1))
    assert scheduler.started is True
    assert scheduler.stopped is True


def test_runtime_exits_promptly_when_shutdown_requested_during_sleep() -> None:
    status = _Status()
    scheduler = _Scheduler()

    runtime = MatrixWorkerRuntime(
        enabled=True,
        status_repository=status,
        scheduler=scheduler,
        clock=_Clock(),
        heartbeat_interval_seconds=30.0,
    )

    async def scenario() -> None:
        task = asyncio.create_task(runtime.run())
        while not status.heartbeats:
            await asyncio.sleep(0)
        runtime.request_shutdown()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(scenario())
    assert status.heartbeats == [("2026-07-13T00:00:01Z", True)]
    assert scheduler.started is True
    assert scheduler.stopped is True
