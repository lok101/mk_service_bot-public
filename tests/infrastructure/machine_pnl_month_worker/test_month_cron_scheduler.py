from __future__ import annotations

import time
from zoneinfo import ZoneInfo

from src.infrastructure.machine_pnl_month_worker.cron_scheduler import (
    ApschedulerMachinePnlMonthBackend,
)


def test_apscheduler_backend_fires_first_24h_interval_job_immediately() -> None:
    fired: list[bool] = []
    backend = ApschedulerMachinePnlMonthBackend()
    backend.add_interval_job(
        hours=24,
        timezone=ZoneInfo("UTC"),
        callback=lambda: fired.append(True),
        job_id="machine_pnl_month_tick_immediate",
    )
    backend.start()
    try:
        deadline = time.monotonic() + 2.0
        while not fired and time.monotonic() < deadline:
            time.sleep(0.05)
        assert fired == [True]
    finally:
        backend.stop()
