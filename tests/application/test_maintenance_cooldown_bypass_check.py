from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.application.machine_operations.maintenance_cooldown_check import (
    is_cooldown_blocking_new_maintenance,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.maintenance_cooldown_policy import is_maintenance_cooldown_bypassed
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot

_MSK = ZoneInfo("Europe/Moscow")
_TECH = TechnicianId("tech-a")
_MACHINE_A = MachineId("vm-a")
_MACHINE_B = MachineId("vm-b")


class _Reader:
    def __init__(self, snapshot: MaintenanceCooldownBypassSnapshot | None) -> None:
        self._snapshot = snapshot

    def get_active(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> MaintenanceCooldownBypassSnapshot | None:
        if self._snapshot is None:
            return None
        effective_checked_at = checked_at or datetime(2026, 7, 9, 6, 1, tzinfo=_MSK)
        if is_maintenance_cooldown_bypassed(
            checked_at=effective_checked_at,
            bypass_service_date=self._snapshot.service_date,
            service_calendar_timezone=_MSK,
            day_end_hour=6,
        ):
            return self._snapshot
        return None


class _LastMaintenanceReader:
    def get_last(self, technician_id: TechnicianId) -> TechnicianLastMaintenanceSnapshot | None:
        _ = technician_id
        return TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=_MACHINE_A,
            completed_at=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        )


def test_bypass_skips_cooldown_block() -> None:
    checked_at = datetime(2026, 7, 8, 10, 5, tzinfo=UTC)
    bypass_reader = _Reader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 8),
            activated_at=datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        ),
    )
    assert (
        is_cooldown_blocking_new_maintenance(
            technician_id=_TECH,
            machine_id=_MACHINE_B,
            checked_at=checked_at,
            last_maintenance_reader=_LastMaintenanceReader(),
            cooldown_minutes=20,
            bypass_reader=bypass_reader,
            service_calendar_timezone=_MSK,
        )
        is False
    )


def test_expired_bypass_does_not_skip_cooldown() -> None:
    checked_at = datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)
    bypass_reader = _Reader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 8),
            activated_at=datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        ),
    )

    class _RecentLastMaintenanceReader:
        def get_last(
            self,
            technician_id: TechnicianId,
        ) -> TechnicianLastMaintenanceSnapshot | None:
            _ = technician_id
            return TechnicianLastMaintenanceSnapshot(
                technician_id=_TECH,
                machine_id=_MACHINE_A,
                completed_at=datetime(2026, 7, 9, 2, 45, tzinfo=UTC),
            )

    assert (
        is_cooldown_blocking_new_maintenance(
            technician_id=_TECH,
            machine_id=_MACHINE_B,
            checked_at=checked_at,
            last_maintenance_reader=_RecentLastMaintenanceReader(),
            cooldown_minutes=20,
            bypass_reader=bypass_reader,
            service_calendar_timezone=_MSK,
        )
        is True
    )


def test_bypass_skips_cooldown_for_checked_at_when_wall_clock_past_expiry() -> None:
    checked_at = datetime(2026, 7, 9, 5, 59, tzinfo=_MSK)
    bypass_reader = _Reader(
        MaintenanceCooldownBypassSnapshot(
            service_date=date(2026, 7, 8),
            activated_at=datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        ),
    )
    assert (
        is_cooldown_blocking_new_maintenance(
            technician_id=_TECH,
            machine_id=_MACHINE_B,
            checked_at=checked_at,
            last_maintenance_reader=_LastMaintenanceReader(),
            cooldown_minutes=20,
            bypass_reader=bypass_reader,
            service_calendar_timezone=_MSK,
        )
        is False
    )
