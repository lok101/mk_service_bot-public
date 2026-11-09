from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.domain.events import DomainEvent
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted
from src.infrastructure.composition.adapters import EventStoreMaintenanceOnOperationalDayLookup
from src.infrastructure.memory import InMemoryEventStore

_MACHINE = MachineId("101")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_OPS_DAY = date(2026, 8, 12)
_TECH = TechnicianId("001")


def test_event_store_lookup_returns_earliest_in_ops_day() -> None:
    store = InMemoryEventStore()
    early = MaintenanceCompleted(
        event_id=EventId("mnt-early"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
    )
    late = MaintenanceCompleted(
        event_id=EventId("mnt-late"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
    )

    store.append(late, expected_version=0)
    store.append(early, expected_version=1)

    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=store)

    got = lookup.find_earliest_for_operational_day(
        _MACHINE,
        _OPS_DAY,
        timezone=_TZ,
        day_end_hour=6,
    )

    assert got is not None
    assert got.event_id == EventId("mnt-early")
    assert got.completed_at == early.completed_at


def test_event_store_lookup_ignores_other_operational_day() -> None:
    store = InMemoryEventStore()
    before_end_hour = MaintenanceCompleted(
        event_id=EventId("mnt-prev-day"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=datetime(2026, 8, 12, 0, 30, tzinfo=UTC),
        occurred_at=datetime(2026, 8, 12, 0, 30, tzinfo=UTC),
    )

    store.append(before_end_hour, expected_version=0)

    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=store)

    got = lookup.find_earliest_for_operational_day(
        _MACHINE,
        _OPS_DAY,
        timezone=_TZ,
        day_end_hour=6,
    )

    assert got is None


def test_event_store_lookup_no_events_returns_none() -> None:
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=InMemoryEventStore())

    assert (
        lookup.find_earliest_for_operational_day(
            _MACHINE,
            _OPS_DAY,
            timezone=_TZ,
            day_end_hour=6,
        )
        is None
    )


class _SpyEventStore:
    def __init__(self) -> None:
        self._inner = InMemoryEventStore()
        self.get_events_calls = 0

    def append(self, event: DomainEvent, *, expected_version: int) -> None:
        self._inner.append(event, expected_version=expected_version)

    def get_events_for_machine(self, machine_id: MachineId) -> list[DomainEvent]:
        self.get_events_calls += 1
        return self._inner.get_events_for_machine(machine_id)

    def list_maintenance_completed_in_completed_at_window(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._inner.list_maintenance_completed_in_completed_at_window(*args, **kwargs)


def test_maintenance_lookup_uses_indexed_query_not_full_replay() -> None:
    store = _SpyEventStore()
    store.append(
        MaintenanceCompleted(
            event_id=EventId("mnt-1"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
            occurred_at=datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
        ),
        expected_version=0,
    )
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=store)

    got = lookup.find_earliest_for_operational_day(
        _MACHINE,
        date(2026, 8, 12),
        timezone=_TZ,
        day_end_hour=6,
    )

    assert got is not None
    assert store.get_events_calls == 0
