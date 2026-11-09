from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.alert_sweep import SweepMicromarketLoadingAlerts
from src.domain.micromarket_loading.order import MicromarketLoadingCycle
from src.infrastructure.micromarket_loading_alert_worker import MicromarketLoadingAlertWorker

_TZ = ZoneInfo("Europe/Moscow")


class _EmptyStore:
    def list_cycles(self) -> tuple[MicromarketLoadingCycle, ...]:
        return ()

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        raise AssertionError("save should not be called")


class _SilentAlerter:
    def send(self, text: str) -> None:
        raise AssertionError(f"unexpected alert: {text}")


class _Names:
    def display_name(self, machine_code: str) -> str:
        return machine_code


def test_alert_worker_runs_loading_sweep_without_assembly_day_path() -> None:
    worker = MicromarketLoadingAlertWorker(
        sweep=SweepMicromarketLoadingAlerts(
            cycle_store=_EmptyStore(),
            alerter=_SilentAlerter(),
            names=_Names(),
            timezone=_TZ,
            day_end_hour=6,
        ),
    )
    assert not hasattr(worker, "assembly_sweep")
    asyncio.run(worker.sweep_once())
