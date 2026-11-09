from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.application.machine_operations.cooldown_bypass_admin import (
    ClearMaintenanceCooldownBypassService,
    DisableMaintenanceCooldownBypassForTodayService,
    GetMaintenanceCooldownBypassStatusService,
)
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot

_MSK = ZoneInfo("Europe/Moscow")
_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


class _FakeStore:
    def __init__(self) -> None:
        self.snapshot: MaintenanceCooldownBypassSnapshot | None = None

    def get_snapshot(self) -> MaintenanceCooldownBypassSnapshot | None:
        return self.snapshot

    def upsert_for_today(
        self,
        *,
        activated_at: datetime,
        reason: str | None,
        service_calendar_timezone: ZoneInfo,
    ) -> MaintenanceCooldownBypassSnapshot:
        _ = service_calendar_timezone
        self.snapshot = MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 8),
            activated_at=activated_at,
            reason=reason,
        )
        return self.snapshot

    def clear(self) -> bool:
        if self.snapshot is None:
            return False
        self.snapshot = None
        return True


def test_disable_for_today_upserts_snapshot() -> None:
    store = _FakeStore()
    service = DisableMaintenanceCooldownBypassForTodayService(
        store=store,
        service_calendar_timezone=_MSK,
        service_day_end_hour=6,
    )
    snapshot = service.execute(activated_at=_NOW, reason="форс-мажор")
    assert snapshot.service_date == date(2026, 7, 8)
    assert snapshot.reason == "форс-мажор"


def test_status_reports_active_bypass() -> None:
    store = _FakeStore()
    DisableMaintenanceCooldownBypassForTodayService(
        store=store,
        service_calendar_timezone=_MSK,
        service_day_end_hour=6,
    ).execute(activated_at=_NOW, reason=None)
    status = GetMaintenanceCooldownBypassStatusService(
        store=store,
        service_calendar_timezone=_MSK,
        service_day_end_hour=6,
        checked_at=_NOW,
    ).execute()
    assert status.active is True
    assert status.expires_at == datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)


def test_clear_returns_false_when_not_active() -> None:
    store = _FakeStore()
    cleared = ClearMaintenanceCooldownBypassService(store=store).execute()
    assert cleared is False


def test_clear_returns_true_when_active() -> None:
    store = _FakeStore()
    DisableMaintenanceCooldownBypassForTodayService(
        store=store,
        service_calendar_timezone=_MSK,
        service_day_end_hour=6,
    ).execute(activated_at=_NOW, reason="форс-мажор")
    cleared = ClearMaintenanceCooldownBypassService(store=store).execute()
    assert cleared is True
    assert store.get_snapshot() is None
