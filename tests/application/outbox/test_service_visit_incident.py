from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tests.application.service_visits.qty_baseline_lookup_fakes import (
    FakeMachineSalesQtyBaselineLookup,
)

from src.application.outbox.service_visit_incident import ServiceVisitIncidentHandler
from src.application.service_visits import (
    AssignedTechnicianRef,
    EnqueueVisitForceNotify,
    NullMachineSalesQtyBaselineLookup,
)
from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.clear_offline import ClearOfflineIncident
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.open_incident_result import (
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.application.service_visits.visit_ids import (
    no_sales_incident_visit_id,
    offline_incident_visit_id,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)
from src.domain.service_visits import ServiceVisitForceNotifyRequested

_MACHINE = MachineId("101")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_AT = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
_OPENED = EventId("off-1")
_STICKY = no_sales_incident_visit_id(_MACHINE)


class _SpyOpener(OpenServiceIncident):
    """Records execute kwargs; subclass satisfies beartype on handler.opener."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> OpenIncidentResult:  # type: ignore[override]
        self.calls.append(kwargs)
        return OpenIncidentResult(
            outcome=VisitForceOutcome.NOOP,
            machine_id=kwargs["machine_id"],
            visit_id=None,
            generation=None,
        )

    def would_suppress_no_sales(self, **kwargs: Any) -> bool:  # type: ignore[override]
        del kwargs
        return False


@dataclass
class _RecordingPublisher:
    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _AlwaysAssignedResolver:
    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None:
        del machine_id
        return AssignedTechnicianRef(
            technician_id=TechnicianId("tech-1"),
            display_name="Иван",
            telegram_user_id=123,
        )


class _DenyVisitPolicy:
    def allows_create_visit_on_no_sales(self, machine_id: MachineId) -> bool:
        del machine_id
        return False


def _handler(
    store: InMemoryServiceVisitStore,
    *,
    baseline: Decimal | None = None,
    min_qty: Decimal = Decimal("0"),
) -> ServiceVisitIncidentHandler:
    lookup: NullMachineSalesQtyBaselineLookup | FakeMachineSalesQtyBaselineLookup
    if baseline is None and min_qty == Decimal("0"):
        lookup = NullMachineSalesQtyBaselineLookup()
    else:
        lookup = FakeMachineSalesQtyBaselineLookup(result=baseline)
    return ServiceVisitIncidentHandler(
        opener=OpenServiceIncident(
            store=store,
            baseline_lookup=lookup,
            min_baseline_qty=min_qty,
        ),
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=_TZ,
        day_end_hour=6,
    )


def _stale_opened(*, event_id: str = "stale-open-1") -> SalesMonitoringNoSalesStaleOpened:
    return SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(event_id),
        machine_id=_MACHINE,
        opened_at=_AT,
        occurred_at=_AT,
        last_sale_at=None,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _sticky_open_extra(store: InMemoryServiceVisitStore) -> None:
    store.upsert(
        ServiceVisit(
            visit_id=_STICKY,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=date(2026, 8, 12),
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.NO_SALES,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_AT,
            updated_at=_AT,
        ),
    )


def test_incident_handler_opens_on_no_sales_stale_opened() -> None:
    """happy: StaleOpened + K=0 → sticky extra."""
    store = InMemoryServiceVisitStore()
    asyncio.run(_handler(store).process(_stale_opened()))
    extra = store.get(_STICKY)
    assert extra is not None
    assert extra.kind is VisitKind.EXTRA_INCIDENT
    assert extra.status is VisitStatus.OPEN
    assert extra.incident_source is IncidentSource.NO_SALES


def test_incident_handler_clears_visit_when_stale_open_below_k() -> None:
    """edge: leftover sticky + low baseline → cleared; нет нового extra."""
    store = InMemoryServiceVisitStore()
    _sticky_open_extra(store)
    asyncio.run(
        _handler(store, baseline=Decimal("2"), min_qty=Decimal("10")).process(_stale_opened()),
    )
    leftover = store.get(_STICKY)
    assert leftover is not None
    assert leftover.status is VisitStatus.CLEARED
    assert leftover.closable is False
    open_extras = [
        visit
        for visit in store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)
        if visit.kind is VisitKind.EXTRA_INCIDENT
    ]
    assert open_extras == []


def test_stale_opened_clears_when_create_visit_false() -> None:
    store = InMemoryServiceVisitStore()
    _sticky_open_extra(store)
    opener = OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
        visit_policy=_DenyVisitPolicy(),
    )
    handler = ServiceVisitIncidentHandler(
        opener=opener,
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=_TZ,
        day_end_hour=6,
    )
    asyncio.run(handler.process(_stale_opened()))
    leftover = store.get(_STICKY)
    assert leftover is not None
    assert leftover.status is VisitStatus.CLEARED
    open_extras = [
        visit
        for visit in store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)
        if visit.kind is VisitKind.EXTRA_INCIDENT
    ]
    assert open_extras == []


def test_incident_handler_clears_on_no_sales_stale_cleared() -> None:
    """happy: StaleCleared → sticky cleared."""
    store = InMemoryServiceVisitStore()
    _sticky_open_extra(store)
    event = SalesMonitoringNoSalesStaleCleared(
        event_id=EventId("stale-clear-1"),
        machine_id=_MACHINE,
        opened_event_id=EventId("stale-open-1"),
        opened_at=_AT,
        cleared_at=_AT,
        occurred_at=_AT,
        last_sale_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    asyncio.run(_handler(store).process(event))
    extra = store.get(_STICKY)
    assert extra is not None
    assert extra.status is VisitStatus.CLEARED
    assert extra.closable is False


def test_incident_handler_ignores_today_yesterday_no_sales_open() -> None:
    """happy: day NoSales не создаёт visit."""
    store = InMemoryServiceVisitStore()
    today = SalesMonitoringTodayNoSales(
        event_id=EventId("ns-1"),
        machine_id=_MACHINE,
        report_day=date(2026, 8, 12),
        occurred_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    yesterday = SalesMonitoringYesterdayNoSales(
        event_id=EventId("ns-y"),
        machine_id=_MACHINE,
        report_day=date(2026, 8, 11),
        occurred_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    handler = _handler(store)
    asyncio.run(handler.process(today))
    asyncio.run(handler.process(yesterday))
    assert store.list_for_machine(_MACHINE) == []
    assert store.get(_STICKY) is None


def test_incident_handler_ignores_decline_and_offline_opened() -> None:
    """регрессия: decline + OfflineOpened no-op."""
    store = InMemoryServiceVisitStore()
    spy = _SpyOpener()
    handler = ServiceVisitIncidentHandler(
        opener=spy,
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=_TZ,
        day_end_hour=6,
    )
    decline = SalesMonitoringYesterdayDecline(
        event_id=EventId("dec-1"),
        machine_id=_MACHINE,
        report_day=date(2026, 8, 11),
        occurred_at=_AT,
        report_sum=Decimal("0"),
        baseline_avg=Decimal("1"),
        drop_percent=0,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    offline = SalesMonitoringOfflineOpened(
        event_id=_OPENED,
        machine_id=_MACHINE,
        opened_at=_AT,
        occurred_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    asyncio.run(handler.process(decline))
    asyncio.run(handler.process(offline))
    assert spy.calls == []
    assert store.list_for_machine(_MACHINE) == []


def test_incident_handler_clears_extra_on_offline_cleared() -> None:
    store = InMemoryServiceVisitStore()
    OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
    ).execute(
        machine_id=_MACHINE,
        ops_day=date(2026, 8, 12),
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_AT,
    )
    event = SalesMonitoringOfflineCleared(
        event_id=EventId("off-clear-1"),
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
        opened_at=_AT,
        cleared_at=_AT,
        occurred_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    asyncio.run(_handler(store).process(event))
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is not None
    assert extra.status is VisitStatus.CLEARED


def test_incident_handler_passes_open_result_to_force_notify() -> None:
    """happy: after StaleOpened opener result is forwarded to force_notify."""
    store = InMemoryServiceVisitStore()
    publisher = _RecordingPublisher()
    handler = ServiceVisitIncidentHandler(
        opener=OpenServiceIncident(
            store=store,
            baseline_lookup=NullMachineSalesQtyBaselineLookup(),
            min_baseline_qty=Decimal("0"),
        ),
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=_TZ,
        day_end_hour=6,
        force_notify=EnqueueVisitForceNotify(
            publisher=publisher,
            resolver=_AlwaysAssignedResolver(),
            enabled=True,
        ),
    )
    asyncio.run(handler.process(_stale_opened()))
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, ServiceVisitForceNotifyRequested)
    assert event.visit_id == _STICKY
    assert event.outcome == VisitForceOutcome.CREATED_EXTRA.value
    assert event.incident_source == IncidentSource.NO_SALES.value
    assert event.occurred_at == _AT
