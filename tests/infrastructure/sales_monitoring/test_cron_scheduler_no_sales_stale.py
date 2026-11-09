from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.infrastructure.sales_monitoring.cron_scheduler import SalesMonitoringCronScheduler

_TZ = ZoneInfo("Asia/Yekaterinburg")


@dataclass
class _FakeBackend:
    interval_jobs: list[dict[str, object]] = field(default_factory=list)

    def add_cron_job(self, **kwargs: object) -> None:
        return None

    def add_interval_job(self, **kwargs: object) -> None:
        self.interval_jobs.append(kwargs)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def _scheduler(**overrides: object) -> SalesMonitoringCronScheduler:
    kw: dict[str, object] = {
        "enabled": True,
        "timezone": _TZ,
        "report_compare_cron": "0 8 * * *",
        "report_today_cron": "0 15 * * *",
        "offline_poll_interval_minutes": 60,
        "offline_poll_from_hour": 8,
        "offline_poll_to_hour": 22,
        "no_sales_eval_interval_minutes": 60,
        "compare_callback": lambda: None,
        "today_callback": lambda: None,
        "offline_callback": lambda: None,
        "no_sales_stale_callback": lambda: None,
        "backend": _FakeBackend(),
    }
    kw.update(overrides)
    return SalesMonitoringCronScheduler(**kw)  # type: ignore[arg-type]


def test_no_sales_stale_eval_tick_respects_hour_window() -> None:
    """edge: вне окна callback не вызывается; внутри — вызывается."""
    calls: list[str] = []

    outside = datetime(2026, 8, 21, 23, 0, tzinfo=_TZ)
    sched_out = _scheduler(
        clock=lambda: outside,
        no_sales_stale_callback=lambda: calls.append("stale"),
    )
    sched_out.run_no_sales_stale_eval_tick()
    assert calls == []

    inside = datetime(2026, 8, 21, 10, 0, tzinfo=_TZ)
    sched_in = _scheduler(
        clock=lambda: inside,
        no_sales_stale_callback=lambda: calls.append("stale"),
    )
    sched_in.run_no_sales_stale_eval_tick()
    assert calls == ["stale"]


def test_no_sales_stale_eval_job_registered_on_start() -> None:
    """happy: start регистрирует job_id sales_monitoring_no_sales_stale_eval."""
    backend = _FakeBackend()
    sched = _scheduler(backend=backend, no_sales_eval_interval_minutes=45)
    sched.start()
    stale_jobs = [
        j for j in backend.interval_jobs if j["job_id"] == "sales_monitoring_no_sales_stale_eval"
    ]
    assert len(stale_jobs) == 1
    assert stale_jobs[0]["minutes"] == 45
