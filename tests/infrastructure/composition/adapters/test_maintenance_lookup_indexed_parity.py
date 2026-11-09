from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import mongomock
import pytest
from tests.infrastructure.composition.adapters.maintenance_lookup_replay_baseline import (
    replay_find_earliest_for_operational_day,
)

from src.domain.events import DomainEvent
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import MaintenanceCompleted, RevisionCompleted
from src.domain.models import RevisionSource
from src.infrastructure.composition.adapters import EventStoreMaintenanceOnOperationalDayLookup
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.mongodb import MongoEventStore

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")


@pytest.fixture(params=["in_memory", "mongo"])
def event_store(request: pytest.FixtureRequest) -> InMemoryEventStore | MongoEventStore:
    if request.param == "in_memory":
        return InMemoryEventStore()
    client = mongomock.MongoClient()
    return MongoEventStore.from_collection(client["test_db"]["machine_events"])


def test_indexed_lookup_matches_replay_baseline_on_ops_day_boundaries(
    event_store: InMemoryEventStore | MongoEventStore,
) -> None:
    tz = ZoneInfo("Asia/Yekaterinburg")
    ops_day = date(2026, 8, 12)
    end_hour = 6
    # window start = 2026-08-12 01:00 UTC for +5 / end_hour 6
    at_start = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)
    before_start = at_start - timedelta(seconds=1)
    at_end_minus = datetime(2026, 8, 13, 0, 59, 59, 999999, tzinfo=UTC)
    at_end = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)

    for event_id, completed_at in (
        (EventId("before"), before_start),
        (EventId("start"), at_start),
        (EventId("inside"), at_end_minus),
        (EventId("at_end"), at_end),
    ):
        event_store.append(
            MaintenanceCompleted(
                event_id=event_id,
                technician_id=_TECH,
                machine_id=_MACHINE,
                completed_at=completed_at,
                occurred_at=completed_at,
            ),
            expected_version=len(event_store.get_events_for_machine(_MACHINE)),
        )

    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=event_store)
    indexed = lookup.find_earliest_for_operational_day(
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=end_hour,
    )
    replay = replay_find_earliest_for_operational_day(
        event_store,
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=end_hour,
    )
    assert indexed == replay
    assert indexed is not None
    assert indexed.event_id == EventId("start")


def test_indexed_lookup_matches_replay_baseline_earliest_same_day(
    event_store: InMemoryEventStore | MongoEventStore,
) -> None:
    tz = ZoneInfo("Europe/Moscow")
    ops_day = date(2026, 8, 15)
    early = datetime(2026, 8, 15, 7, 0, tzinfo=UTC)
    late = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    event_store.append(
        MaintenanceCompleted(
            event_id=EventId("late"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=late,
            occurred_at=late,
        ),
        expected_version=0,
    )
    event_store.append(
        MaintenanceCompleted(
            event_id=EventId("early"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=early,
            occurred_at=early,
        ),
        expected_version=1,
    )
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=event_store)
    indexed = lookup.find_earliest_for_operational_day(
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    replay = replay_find_earliest_for_operational_day(
        event_store,
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    assert indexed == replay
    assert indexed is not None
    assert indexed.event_id == EventId("early")


def test_indexed_lookup_matches_replay_baseline_empty_stream(
    event_store: InMemoryEventStore | MongoEventStore,
) -> None:
    tz = ZoneInfo("Asia/Yekaterinburg")
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=event_store)
    ops_day = date(2026, 8, 12)
    indexed = lookup.find_earliest_for_operational_day(
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    replay = replay_find_earliest_for_operational_day(
        event_store,
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    assert indexed is None
    assert replay is None


def test_indexed_lookup_matches_replay_baseline_mixed_event_types(
    event_store: InMemoryEventStore | MongoEventStore,
) -> None:
    tz = ZoneInfo("Asia/Yekaterinburg")
    ops_day = date(2026, 8, 12)
    at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    event_store.append(
        RevisionCompleted(
            event_id=EventId("rev-1"),
            revision_id=RevisionId("r1"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=at,
            occurred_at=at,
            source=RevisionSource.GOOGLE_FORM,
            form_id="f",
            form_token="t",
        ),
        expected_version=0,
    )
    event_store.append(
        MaintenanceCompleted(
            event_id=EventId("mnt-1"),
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=at,
            occurred_at=at,
        ),
        expected_version=1,
    )
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=event_store)
    indexed = lookup.find_earliest_for_operational_day(
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    replay = replay_find_earliest_for_operational_day(
        event_store,
        _MACHINE,
        ops_day,
        timezone=tz,
        day_end_hour=6,
    )
    assert indexed == replay
    assert indexed is not None
    assert indexed.event_id == EventId("mnt-1")


class _BrokenQueryStore:
    def __init__(self) -> None:
        self._inner = InMemoryEventStore()

    def append(self, event: DomainEvent, *, expected_version: int) -> None:
        self._inner.append(event, expected_version=expected_version)

    def get_events_for_machine(self, machine_id: MachineId) -> list[DomainEvent]:
        return self._inner.get_events_for_machine(machine_id)

    def list_maintenance_completed_in_completed_at_window(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("indexed query unavailable")


def test_maintenance_lookup_propagates_query_failure_without_replay_fallback() -> None:
    store = _BrokenQueryStore()
    lookup = EventStoreMaintenanceOnOperationalDayLookup(event_store=store)

    with patch.object(store, "get_events_for_machine") as replay:
        with pytest.raises(RuntimeError, match="indexed query unavailable"):
            lookup.find_earliest_for_operational_day(
                MachineId("101"),
                date(2026, 8, 12),
                timezone=ZoneInfo("Asia/Yekaterinburg"),
                day_end_hour=6,
            )
        replay.assert_not_called()
