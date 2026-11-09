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


def test_status_board_rotate_job_registered() -> None:
    """happy: start регистрирует weekly job_id и crontab из ctor."""
    backend = _Backend()
    sched = _base(
        backend=backend,
        status_board_cron="0 8 * * 1",
        status_board_rotate_callback=lambda: None,
    )
    sched.start()
    jobs = [j for j in backend.cron_jobs if j["job_id"] == "sales_monitoring_no_sales_status_board"]
    assert len(jobs) == 1
    assert jobs[0]["crontab"] == "0 8 * * 1"


def test_status_board_rotate_callback_invoked_from_job() -> None:
    """happy: registered callback is the ctor rotate callback (identity)."""
    calls: list[str] = []
    backend = _Backend()
    sched = _base(
        backend=backend,
        status_board_rotate_callback=lambda: calls.append("rotate"),
    )
    sched.start()
    job = next(
        j for j in backend.cron_jobs if j["job_id"] == "sales_monitoring_no_sales_status_board"
    )
    callback = job["callback"]
    assert callable(callback)
    callback()
    assert calls == ["rotate"]


def test_status_board_scheduler_default_cron_daily_0800() -> None:
    """happy: ctor без status_board_cron регистрирует daily 0 8 * * *."""
    backend = _Backend()
    sched = _base(backend=backend)
    sched.start()
    jobs = [j for j in backend.cron_jobs if j["job_id"] == "sales_monitoring_no_sales_status_board"]
    assert len(jobs) == 1
    assert jobs[0]["crontab"] == "0 8 * * *"
