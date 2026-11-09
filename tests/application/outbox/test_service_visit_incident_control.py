from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.application.outbox.service_visit_incident import ServiceVisitIncidentHandler
from src.application.sales_monitoring.no_sales_control import (
    NoSalesVisitBlockLookup,
    engineer_wait_document_id,
    mute_cancel_document_id,
    mute_document_id,
)
from src.application.service_visits import (
    AssignedTechnicianRef,
    EnqueueVisitForceNotify,
)
from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.clear_offline import ClearOfflineIncident
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.open_incident_result import (
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.application.service_visits.visit_ids import no_sales_incident_visit_id
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring import SalesMonitoringNoSalesStaleOpened
from src.infrastructure.sales_monitoring.memory_audit import (
    InMemorySalesMonitoringAuditStore,
)

_MACHINE = MachineId("501")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_AT = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)


class _RecordingOpener(OpenServiceIncident):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, **kwargs: Any) -> OpenIncidentResult:  # type: ignore[override]
        visit_id = kwargs["visit_id"]
        assert isinstance(visit_id, str)
        self.calls.append(visit_id)
        return OpenIncidentResult(
            outcome=VisitForceOutcome.CREATED_EXTRA,
            machine_id=kwargs["machine_id"],
            visit_id=visit_id,
            generation="g1",
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


def _handler(
    *,
    opener: _RecordingOpener,
    control: NoSalesVisitBlockLookup | None = None,
) -> ServiceVisitIncidentHandler:
    store = InMemoryServiceVisitStore()
    return ServiceVisitIncidentHandler(
        opener=opener,
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=_TZ,
        day_end_hour=6,
        control=control,
    )


def _stale_opened() -> SalesMonitoringNoSalesStaleOpened:
    return SalesMonitoringNoSalesStaleOpened(
        event_id=EventId("stale-open-1"),
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


def test_stale_opened_skips_visit_when_mute_active() -> None:
    opener = _RecordingOpener()
    store = InMemorySalesMonitoringAuditStore()
    opened = "stale-open-1"
    store.upsert_control(
        {
            "_id": mute_document_id(_MACHINE, opened),
            "kind": "no_sales_mute",
            "machine_id": _MACHINE.value,
        }
    )
    handler = _handler(opener=opener, control=store)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == []


def test_stale_opened_skips_visit_when_engineer_wait_active() -> None:
    opener = _RecordingOpener()
    store = InMemorySalesMonitoringAuditStore()
    opened = "stale-open-1"
    store.upsert_control(
        {
            "_id": engineer_wait_document_id(_MACHINE, opened),
            "kind": "no_sales_engineer_wait",
            "machine_id": _MACHINE.value,
        }
    )
    handler = _handler(opener=opener, control=store)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == []


def test_stale_opened_opens_visit_after_mute_cancel() -> None:
    opener = _RecordingOpener()
    store = InMemorySalesMonitoringAuditStore()
    opened = "stale-open-1"
    mute_id = mute_document_id(_MACHINE, opened)
    store.upsert_control(
        {
            "_id": mute_id,
            "kind": "no_sales_mute",
            "machine_id": _MACHINE.value,
        }
    )
    store.upsert_control(
        {
            "_id": mute_cancel_document_id(_MACHINE, mute_id),
            "kind": "no_sales_mute_cancel",
            "machine_id": _MACHINE.value,
        }
    )
    handler = _handler(opener=opener, control=store)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == [no_sales_incident_visit_id(_MACHINE)]


def test_stale_opened_opens_visit_when_mute_targets_other_opened_event_id() -> None:
    opener = _RecordingOpener()
    store = InMemorySalesMonitoringAuditStore()
    store.upsert_control(
        {
            "_id": mute_document_id(_MACHINE, "evt-open-other"),
            "kind": "no_sales_mute",
            "machine_id": _MACHINE.value,
        }
    )
    handler = _handler(opener=opener, control=store)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == [no_sales_incident_visit_id(_MACHINE)]


class _FlipBlockControl:
    def __init__(self) -> None:
        self._calls = 0

    def blocks_technician_visit(self, *, machine_id: MachineId, opened_event_id: str) -> bool:
        del machine_id, opened_event_id
        self._calls += 1
        return self._calls >= 2


class _RecordingClearer(ClearNoSalesIncident):
    def __init__(self) -> None:
        super().__init__(store=InMemoryServiceVisitStore())
        self.calls: list[MachineId] = []

    def execute(self, *, machine_id: MachineId, now: object) -> None:  # type: ignore[override]
        del now
        self.calls.append(machine_id)


def _race_handler(
    *,
    opener: _RecordingOpener,
    clearer: _RecordingClearer,
    publisher: _RecordingPublisher,
) -> ServiceVisitIncidentHandler:
    return ServiceVisitIncidentHandler(
        opener=opener,
        clearer=ClearOfflineIncident(store=InMemoryServiceVisitStore()),
        no_sales_clearer=clearer,
        timezone=_TZ,
        day_end_hour=6,
        force_notify=EnqueueVisitForceNotify(
            publisher=publisher,
            resolver=_AlwaysAssignedResolver(),
            enabled=True,
        ),
        control=_FlipBlockControl(),
    )


def test_stale_opened_clears_when_mute_appears_after_first_check() -> None:
    """edge: control allows open, then blocks — clearer runs, force_notify skipped."""
    opener = _RecordingOpener()
    clearer = _RecordingClearer()
    publisher = _RecordingPublisher()
    handler = _race_handler(opener=opener, clearer=clearer, publisher=publisher)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == [no_sales_incident_visit_id(_MACHINE)]
    assert clearer.calls == [_MACHINE]
    assert publisher.events == []


def test_stale_opened_clears_when_engineer_wait_appears_after_first_check() -> None:
    """edge: second check blocks (engineer-wait race shares re-check path)."""
    opener = _RecordingOpener()
    clearer = _RecordingClearer()
    publisher = _RecordingPublisher()
    handler = _race_handler(opener=opener, clearer=clearer, publisher=publisher)
    asyncio.run(handler.process(_stale_opened()))
    assert opener.calls == [no_sales_incident_visit_id(_MACHINE)]
    assert clearer.calls == [_MACHINE]
    assert publisher.events == []
