from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tests.application.service_visits.maintenance_lookup_fakes import (
    FakeMaintenanceOnOperationalDayLookup,
)

from src.application.service_visits.null_maintenance_lookup import (
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.ports import (
    MaintenanceOnOperationalDayLookup,
    MaintenanceOnOperationalDaySnapshot,
)
from src.domain.ids import EventId, MachineId, TechnicianId

_MACHINE = MachineId("101")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_OPS_DAY = date(2026, 8, 12)
_TECH = TechnicianId("001")
_EVENT = EventId("mnt-1")
_AT = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
_SNAPSHOT = MaintenanceOnOperationalDaySnapshot(
    event_id=_EVENT,
    technician_id=_TECH,
    completed_at=_AT,
)


def test_null_lookup_is_protocol_instance() -> None:
    lookup: MaintenanceOnOperationalDayLookup = NullMaintenanceOnOperationalDayLookup()
    assert isinstance(lookup, MaintenanceOnOperationalDayLookup)


def test_null_lookup_returns_none() -> None:
    lookup = NullMaintenanceOnOperationalDayLookup()
    assert (
        lookup.find_earliest_for_operational_day(
            _MACHINE,
            _OPS_DAY,
            timezone=_TZ,
            day_end_hour=6,
        )
        is None
    )


def test_fake_lookup_returns_configured_snapshot() -> None:
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {(_MACHINE, _OPS_DAY): _SNAPSHOT},
    )
    got = lookup.find_earliest_for_operational_day(
        _MACHINE,
        _OPS_DAY,
        timezone=_TZ,
        day_end_hour=6,
    )
    assert got == _SNAPSHOT


def test_fake_lookup_missing_key_returns_none() -> None:
    lookup = FakeMaintenanceOnOperationalDayLookup({})
    assert (
        lookup.find_earliest_for_operational_day(
            _MACHINE,
            _OPS_DAY,
            timezone=_TZ,
            day_end_hour=6,
        )
        is None
    )
