from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from src.infrastructure.sales_monitoring.cron_scheduler import SalesMonitoringCronScheduler


@dataclass
class _Backend:
    cron_jobs: list[dict[str, object]] = field(default_factory=list)

    def add_cron_job(self, **kwargs: object) -> None:
        self.cron_jobs.append(kwargs)

    def add_interval_job(self, **kwargs: object) -> None:
        return None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def _base(**overrides: object) -> SalesMonitoringCronScheduler:
    kw = dict(
        enabled=True,
        timezone=ZoneInfo("UTC"),
        report_compare_cron="0 8 * * *",
        report_today_cron="0 15 * * *",
        offline_poll_interval_minutes=60,
        offline_poll_from_hour=8,
        offline_poll_to_hour=22,
        no_sales_eval_interval_minutes=60,
        compare_callback=lambda: None,
        today_callback=lambda: None,
        offline_callback=lambda: None,
        no_sales_stale_callback=lambda: None,
        backend=_Backend(),
        sales_sheet_export_enabled=False,
        sales_sheet_export_cron="0 1 * * *",
        export_callback=lambda: None,
    )
    kw.update(overrides)
    return SalesMonitoringCronScheduler(**kw)  # type: ignore[arg-type]


def test_export_cron_skipped_when_disabled() -> None:
    backend = _Backend()
    sched = _base(backend=backend, sales_sheet_export_enabled=False)
    sched.start()
    ids = [j["job_id"] for j in backend.cron_jobs]
    assert "sales_monitoring_sales_sheet_export" not in ids


def test_export_cron_registered_when_enabled() -> None:
    backend = _Backend()
    sched = _base(backend=backend, sales_sheet_export_enabled=True)
    sched.start()
    export_jobs = [
        j for j in backend.cron_jobs if j["job_id"] == "sales_monitoring_sales_sheet_export"
    ]
    assert len(export_jobs) == 1
    assert export_jobs[0]["crontab"] == "0 1 * * *"
    assert export_jobs[0]["max_instances"] == 1
