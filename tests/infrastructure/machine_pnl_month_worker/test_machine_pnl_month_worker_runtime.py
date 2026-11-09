from __future__ import annotations

import asyncio

from src.infrastructure.machine_pnl_month_worker.worker_runtime import (
    MachinePnlMonthWorkerRuntime,
)


class _FlakyStatus:
    def __init__(self) -> None:
        self.calls = 0
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("mongo blip")
        self.heartbeats.append((at, enabled))


class _Scheduler:
    def start(self) -> None: ...

    def stop(self) -> None: ...


class _Clock:
    def __init__(self) -> None:
        self._n = 0

    def now_utc_iso(self) -> str:
        self._n += 1
        return f"2026-08-28T00:00:0{self._n}Z"


def test_machine_pnl_month_worker_heartbeat_failure_continues_loop() -> None:
    status = _FlakyStatus()
    runtime = MachinePnlMonthWorkerRuntime(
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
