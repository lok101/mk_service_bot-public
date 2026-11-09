from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.null_maintenance_lookup import (
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.visit_ids import (
    no_sales_incident_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
_DAY_BASED = "incident:no_sales:101:2026-08-10"


def _extra(*, visit_id: str, due: date = _WED) -> ServiceVisit:
    return ServiceVisit(
        visit_id=visit_id,
        machine_id=_MACHINE,
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=due,
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


def test_clear_no_sales_clears_sticky_extra() -> None:
    """happy: sticky open → cleared без оплаты."""
    store = InMemoryServiceVisitStore()
    sticky = no_sales_incident_visit_id(_MACHINE)
    store.upsert(_extra(visit_id=sticky))
    ClearNoSalesIncident(store=store).execute(machine_id=_MACHINE, now=_NOW)
    visit = store.get(sticky)
    assert visit is not None
    assert visit.status is VisitStatus.CLEARED
    assert visit.closable is False
    assert visit.close_type is None


def test_clear_no_sales_clears_day_based_extra() -> None:
    """edge: legacy day-based open → cleared; sticky absent ok."""
    store = InMemoryServiceVisitStore()
    store.upsert(_extra(visit_id=_DAY_BASED, due=date(2026, 8, 10)))
    ClearNoSalesIncident(store=store).execute(machine_id=_MACHINE, now=_NOW)
    visit = store.get(_DAY_BASED)
    assert visit is not None
    assert visit.status is VisitStatus.CLEARED
    assert visit.closable is False


def test_clear_no_sales_unboosts_scheduled() -> None:
    """happy: priority_boost на SCHEDULED снимается (паритет offline)."""
    store = InMemoryServiceVisitStore()
    MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=ZoneInfo("UTC"),
        day_end_hour=6,
    ).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None
    store.upsert(replace(slot, priority_boost=True, updated_at=_NOW))
    ClearNoSalesIncident(store=store).execute(machine_id=_MACHINE, now=_NOW)
    cleared_slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert cleared_slot is not None
    assert cleared_slot.priority_boost is False
