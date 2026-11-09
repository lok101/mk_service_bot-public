from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.application.service_visits.detach_on_loading_rollback import (
    DetachVisitTaskOnLoadingRollback,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId

_MACHINE = MachineId("701")
_OPS_DAY = date(2026, 10, 13)
_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=ZoneInfo("Asia/Yekaterinburg"))
_VISIT_ID = scheduled_visit_id(_MACHINE, _OPS_DAY)


def _open_visit(
    *,
    sources: frozenset[VisitTaskSource],
    loading_order_id: str | None,
) -> ServiceVisit:
    return ServiceVisit(
        visit_id=_VISIT_ID,
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
        sources=sources,
        loading_order_id=loading_order_id,
    )


def test_rollback_clears_loading_only_visit_task() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        _open_visit(
            sources=frozenset({VisitTaskSource.MICROMARKET_LOADING}),
            loading_order_id="order-1",
        )
    )

    DetachVisitTaskOnLoadingRollback(store=store).execute(
        machine_id=_MACHINE,
        visit_id=_VISIT_ID,
        now=_NOW,
    )

    visit = store.get(_VISIT_ID)
    assert visit is not None
    assert visit.status is VisitStatus.CLEARED
    assert visit.closable is False
    assert VisitTaskSource.MICROMARKET_LOADING not in visit.sources
    assert visit.loading_order_id is None


def test_rollback_keeps_visit_when_other_sources() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        _open_visit(
            sources=frozenset({VisitTaskSource.ROSTER, VisitTaskSource.MICROMARKET_LOADING}),
            loading_order_id="order-1",
        )
    )

    DetachVisitTaskOnLoadingRollback(store=store).execute(
        machine_id=_MACHINE,
        visit_id=_VISIT_ID,
        now=_NOW,
    )

    visit = store.get(_VISIT_ID)
    assert visit is not None
    assert visit.status is VisitStatus.OPEN
    assert visit.closable is True
    assert VisitTaskSource.ROSTER in visit.sources
    assert VisitTaskSource.MICROMARKET_LOADING not in visit.sources
    assert visit.loading_order_id is None


def test_detach_noop_when_visit_id_missing() -> None:
    store = InMemoryServiceVisitStore()
    DetachVisitTaskOnLoadingRollback(store=store).execute(
        machine_id=_MACHINE,
        visit_id=None,
        now=_NOW,
    )
    assert store.list_for_machine(_MACHINE) == []


def test_detach_noop_when_visit_already_terminal() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        ServiceVisit(
            visit_id=_VISIT_ID,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_OPS_DAY,
            status=VisitStatus.COMPLETED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=_NOW,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
            sources=frozenset({VisitTaskSource.MICROMARKET_LOADING}),
            loading_order_id="order-1",
        )
    )

    DetachVisitTaskOnLoadingRollback(store=store).execute(
        machine_id=_MACHINE,
        visit_id=_VISIT_ID,
        now=_NOW,
    )

    visit = store.get(_VISIT_ID)
    assert visit is not None
    assert visit.status is VisitStatus.COMPLETED
    assert visit.loading_order_id == "order-1"


def test_detach_idempotent_second_call() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        _open_visit(
            sources=frozenset({VisitTaskSource.MICROMARKET_LOADING}),
            loading_order_id="order-1",
        )
    )
    uc = DetachVisitTaskOnLoadingRollback(store=store)
    uc.execute(machine_id=_MACHINE, visit_id=_VISIT_ID, now=_NOW)
    uc.execute(machine_id=_MACHINE, visit_id=_VISIT_ID, now=_NOW)
    visit = store.get(_VISIT_ID)
    assert visit is not None
    assert visit.status is VisitStatus.CLEARED
