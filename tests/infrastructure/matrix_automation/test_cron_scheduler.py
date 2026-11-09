from __future__ import annotations

from zoneinfo import ZoneInfo

from src.infrastructure.matrix_automation.cron_scheduler import MatrixCronScheduler


class _FakeBackend:
    def __init__(self) -> None:
        self.jobs: list[tuple[int, ZoneInfo, object]] = []
        self.started = False
        self.stopped = False

    def add_daily_job(
        self,
        *,
        hour: int,
        timezone: ZoneInfo,
        callback: object,
    ) -> None:
        self.jobs.append((hour, timezone, callback))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_enabled_scheduler_registers_one_daily_job_at_local_hour() -> None:
    backend = _FakeBackend()
    calls: list[str] = []
    scheduler = MatrixCronScheduler(
        enabled=True,
        hour=3,
        timezone=ZoneInfo("Europe/Moscow"),
        callback=lambda: calls.append("run"),
        backend=backend,
    )

    scheduler.start()

    assert len(backend.jobs) == 1
    hour, timezone, callback = backend.jobs[0]
    assert hour == 3
    assert timezone == ZoneInfo("Europe/Moscow")
    assert backend.started is True
    callback()  # type: ignore[operator]
    assert calls == ["run"]

    scheduler.stop()
    assert backend.stopped is True


def test_disabled_scheduler_registers_no_job() -> None:
    backend = _FakeBackend()
    scheduler = MatrixCronScheduler(
        enabled=False,
        hour=3,
        timezone=ZoneInfo("Europe/Moscow"),
        callback=lambda: None,
        backend=backend,
    )

    scheduler.start()

    assert backend.jobs == []
    assert backend.started is False


def test_scheduler_uses_service_display_timezone_not_machine_timezone() -> None:
    backend = _FakeBackend()
    service_tz = ZoneInfo("Asia/Yekaterinburg")
    scheduler = MatrixCronScheduler(
        enabled=True,
        hour=5,
        timezone=service_tz,
        callback=lambda: None,
        backend=backend,
    )

    scheduler.start()

    assert backend.jobs[0][1] is service_tz
    assert str(backend.jobs[0][1]) == "Asia/Yekaterinburg"
