from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.ids import MachineId, TechnicianId
from src.domain.maintenance_cooldown_policy import (
    is_maintenance_cooldown_active,
    is_maintenance_cooldown_bypassed,
    maintenance_cooldown_bypass_expires_at,
)
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot

_TECH = TechnicianId("tech-a")
_MACHINE_A = MachineId("vm-a")
_MACHINE_B = MachineId("vm-b")
_T0 = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def test_cooldown_inactive_when_minutes_zero() -> None:
    snapshot = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_A,
        completed_at=_T0,
    )
    assert (
        is_maintenance_cooldown_active(
            technician_id=_TECH,
            current_machine_id=_MACHINE_B,
            checked_at=_T0 + timedelta(minutes=1),
            last_maintenance=snapshot,
            cooldown_minutes=0,
        )
        is False
    )


def test_cooldown_inactive_when_no_last_maintenance() -> None:
    assert (
        is_maintenance_cooldown_active(
            technician_id=_TECH,
            current_machine_id=_MACHINE_B,
            checked_at=_T0,
            last_maintenance=None,
            cooldown_minutes=20,
        )
        is False
    )


def test_cooldown_inactive_for_same_machine() -> None:
    snapshot = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_A,
        completed_at=_T0,
    )
    assert (
        is_maintenance_cooldown_active(
            technician_id=_TECH,
            current_machine_id=_MACHINE_A,
            checked_at=_T0 + timedelta(minutes=5),
            last_maintenance=snapshot,
            cooldown_minutes=20,
        )
        is False
    )


def test_cooldown_active_within_window_on_different_machine() -> None:
    snapshot = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_A,
        completed_at=_T0,
    )
    assert (
        is_maintenance_cooldown_active(
            technician_id=_TECH,
            current_machine_id=_MACHINE_B,
            checked_at=_T0 + timedelta(minutes=19),
            last_maintenance=snapshot,
            cooldown_minutes=20,
        )
        is True
    )


def test_cooldown_inactive_after_window_expired() -> None:
    snapshot = TechnicianLastMaintenanceSnapshot(
        technician_id=_TECH,
        machine_id=_MACHINE_A,
        completed_at=_T0,
    )
    assert (
        is_maintenance_cooldown_active(
            technician_id=_TECH,
            current_machine_id=_MACHINE_B,
            checked_at=_T0 + timedelta(minutes=20),
            last_maintenance=snapshot,
            cooldown_minutes=20,
        )
        is False
    )


_MSK = ZoneInfo("Europe/Moscow")
_SERVICE_DATE = date(2026, 7, 8)


def test_bypass_end_hour_constant_removed() -> None:
    import src.domain.maintenance_cooldown_policy as policy

    name = "MAINTENANCE_COOLDOWN_BYPASS" + "_END_HOUR"
    assert not hasattr(policy, name)


def test_bypass_expires_at_next_operational_day_start() -> None:
    expires = maintenance_cooldown_bypass_expires_at(
        _SERVICE_DATE,
        _MSK,
        day_end_hour=6,
    )
    assert expires == datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)


def test_bypass_activation_at_0200_expires_at_nearest_end_hour() -> None:
    from src.domain.calendar import operational_day

    activated_at = datetime(2026, 7, 9, 2, 0, tzinfo=_MSK)
    ops_day = operational_day(activated_at, _MSK, 6)
    assert ops_day == date(2026, 7, 8)
    expires = maintenance_cooldown_bypass_expires_at(
        ops_day,
        _MSK,
        day_end_hour=6,
    )
    assert expires == datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)


def test_bypass_expires_at_next_day_six_am_local() -> None:
    expires = maintenance_cooldown_bypass_expires_at(
        _SERVICE_DATE,
        _MSK,
        day_end_hour=6,
    )
    assert expires == datetime(2026, 7, 9, 6, 0, tzinfo=_MSK)


def test_bypass_active_one_second_before_expiry() -> None:
    expires = maintenance_cooldown_bypass_expires_at(
        _SERVICE_DATE,
        _MSK,
        day_end_hour=6,
    )
    checked_at = expires - timedelta(seconds=1)
    assert (
        is_maintenance_cooldown_bypassed(
            checked_at=checked_at,
            bypass_service_date=_SERVICE_DATE,
            service_calendar_timezone=_MSK,
            day_end_hour=6,
        )
        is True
    )


def test_bypass_inactive_at_exact_expiry() -> None:
    expires = maintenance_cooldown_bypass_expires_at(
        _SERVICE_DATE,
        _MSK,
        day_end_hour=6,
    )
    assert (
        is_maintenance_cooldown_bypassed(
            checked_at=expires,
            bypass_service_date=_SERVICE_DATE,
            service_calendar_timezone=_MSK,
            day_end_hour=6,
        )
        is False
    )
