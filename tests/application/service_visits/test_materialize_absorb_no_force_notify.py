from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.application.service_visits import (
    IncidentSource,
    MachineSchedule,
    MaterializeScheduledVisits,
    NullMaintenanceOnOperationalDayLookup,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.visit_ids import no_sales_incident_visit_id
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
_TZ = ZoneInfo("UTC")


def _materialize(store: InMemoryServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=6,
    )


def test_materialize_absorb_does_not_call_enqueue_force_notify() -> None:
    """edge: absorb extra→boost не идёт через EnqueueVisitForceNotify."""
    store = InMemoryServiceVisitStore()
    visit_id = no_sales_incident_visit_id(_MACHINE)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=_WED,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.NO_SALES,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    result = _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    assert result.extras_absorbed >= 1
    sig = inspect.signature(MaterializeScheduledVisits.execute)
    assert "force_notify" not in sig.parameters
