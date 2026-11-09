from __future__ import annotations

import asyncio

from src.infrastructure.machine_pnl_month_worker.worker_runtime import (
    MachinePnlMonthWorkerRuntime,
)


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
    runtime: MachinePnlMonthWorkerRuntime,
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
    runtime = MachinePnlMonthWorkerRuntime(
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
