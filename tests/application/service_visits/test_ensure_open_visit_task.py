from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.ensure_open_visit_task import EnsureOpenVisitTask
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId
from src.domain.micromarket_loading.order import MicromarketLoadingCycle

_MACHINE = MachineId("701")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_OPS_DAY = date(2026, 10, 13)  # Tuesday
_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=_TZ)


def test_ensure_open_creates_visit_when_no_slot() -> None:
    store = InMemoryServiceVisitStore()
    result = EnsureOpenVisitTask(store=store).execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.MICROMARKET_LOADING,
        now=_NOW,
    )
    assert result.created is True
    visit = store.get(result.visit_id)
    assert visit is not None
    assert visit.visit_id == scheduled_visit_id(_MACHINE, _OPS_DAY)
    assert visit.status is VisitStatus.OPEN
    assert visit.due_date == _OPS_DAY
    assert visit.kind is VisitKind.SCHEDULED
    assert visit.closable is True
    assert VisitTaskSource.MICROMARKET_LOADING in visit.sources
    assert len(store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)) == 1


def test_ensure_then_materialize_keeps_one_open_visit_and_order_link() -> None:
    """Regression: lazy/loading ensure before roster must not fork a second SCHEDULED."""
    store = InMemoryServiceVisitStore()
    ensure = EnsureOpenVisitTask(store=store)
    first = ensure.execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.MICROMARKET_LOADING,
        now=_NOW,
        loading_order_id="order-coalesce",
    )
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE.value)
    cycle.open_order(
        order_id="order-coalesce",
        move_id="move-1",
        lines=(),
        opened_at=_NOW,
        timezone=_TZ,
        day_end_hour=6,
    )
    cycle.link_visit(first.visit_id)

    MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=6,
    ).execute(
        due_date=_OPS_DAY,
        catalog=(MachineSchedule(_MACHINE, frozenset({_OPS_DAY.weekday()})),),
        now=_NOW,
    )

    open_visits = store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)
    assert len(open_visits) == 1
    canonical = scheduled_visit_id(_MACHINE, _OPS_DAY)
    assert open_visits[0].visit_id == canonical
    assert open_visits[0].loading_order_id == "order-coalesce"
    assert VisitTaskSource.MICROMARKET_LOADING in open_visits[0].sources

    second = ensure.execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.FIELD_ACTIVITY,
        now=_NOW,
    )
    assert second.visit_id == first.visit_id == canonical
    cycle.link_visit(second.visit_id)  # same id — no ValueError
    assert cycle.visit_id == canonical


def test_ensure_open_reuses_open_scheduled_same_day() -> None:
    store = InMemoryServiceVisitStore()
    scheduled_id = scheduled_visit_id(_MACHINE, _OPS_DAY)
    store.upsert(
        ServiceVisit(
            visit_id=scheduled_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_OPS_DAY,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    result = EnsureOpenVisitTask(store=store).execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.MICROMARKET_LOADING,
        now=_NOW,
        loading_order_id="order-1",
    )
    assert result.created is False
    assert result.visit_id == scheduled_id
    open_visits = store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)
    assert len(open_visits) == 1
    visit = store.get(scheduled_id)
    assert visit is not None
    assert VisitTaskSource.MICROMARKET_LOADING in visit.sources
    assert visit.loading_order_id == "order-1"


def test_ensure_open_idempotent_and_attaches_order_id() -> None:
    store = InMemoryServiceVisitStore()
    first = EnsureOpenVisitTask(store=store).execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.FIELD_ACTIVITY,
        now=_NOW,
    )
    second = EnsureOpenVisitTask(store=store).execute(
        machine_id=_MACHINE,
        ops_day=_OPS_DAY,
        source=VisitTaskSource.MICROMARKET_LOADING,
        now=_NOW,
        loading_order_id="order-9",
    )
    assert first.visit_id == second.visit_id
    assert second.created is False
    visit = store.get(first.visit_id)
    assert visit is not None
    assert visit.loading_order_id == "order-9"
    assert VisitTaskSource.FIELD_ACTIVITY in visit.sources
    assert VisitTaskSource.MICROMARKET_LOADING in visit.sources
    assert len(store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)) == 1
