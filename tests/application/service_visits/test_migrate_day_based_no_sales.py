from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.migrate_day_based_no_sales import (
    MigrateDayBasedNoSalesVisits,
)
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.visit_ids import no_sales_incident_visit_id
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_OTHER = MachineId("202")
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
_DAY_BASED = "incident:no_sales:101:2026-08-10"


def _extra(*, visit_id: str, machine_id: MachineId = _MACHINE) -> ServiceVisit:
    return ServiceVisit(
        visit_id=visit_id,
        machine_id=machine_id,
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=date(2026, 8, 10),
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


def test_migrate_clears_day_based_no_sales_extras() -> None:
    """happy: day-based → cleared; sticky open не трогать; return count."""
    store = InMemoryServiceVisitStore()
    sticky = no_sales_incident_visit_id(_MACHINE)
    store.upsert(_extra(visit_id=sticky))
    store.upsert(_extra(visit_id=_DAY_BASED))
    store.upsert(
        _extra(visit_id="incident:no_sales:202:2026-08-09", machine_id=_OTHER),
    )
    cleared = MigrateDayBasedNoSalesVisits(store=store).execute(now=_NOW)
    assert cleared == 2
    sticky_visit = store.get(sticky)
    assert sticky_visit is not None
    assert sticky_visit.status is VisitStatus.OPEN
    day = store.get(_DAY_BASED)
    assert day is not None
    assert day.status is VisitStatus.CLEARED
    assert day.closable is False
    assert day.close_type is None
    other = store.get("incident:no_sales:202:2026-08-09")
    assert other is not None
    assert other.status is VisitStatus.CLEARED
