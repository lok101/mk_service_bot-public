from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.application.outbox.no_sales_incident_control import NoSalesIncidentControlHandler
from src.application.sales_monitoring.no_sales_control import (
    engineer_wait_document_id,
    mute_document_id,
)
from src.domain.ids import EventId, MachineId
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlRequested
from src.infrastructure.mongodb.sales_monitoring_serialization import (
    sales_monitoring_event_from_document,
    sales_monitoring_event_to_document,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE = MachineId("501")
_OPENED = "evt-open-1"
_OCCURRED = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class _RecordingClearer:
    def __init__(self) -> None:
        self.calls: list[MachineId] = []

    def execute(self, *, machine_id: MachineId, now: datetime) -> None:
        del now
        self.calls.append(machine_id)


def _mute_requested() -> NoSalesIncidentControlRequested:
    return NoSalesIncidentControlRequested(
        event_id=EventId(mute_document_id(_MACHINE, _OPENED)),
        occurred_at=_OCCURRED,
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
        action="mute",
        mute_event_id=None,
    )


def _engineer_requested() -> NoSalesIncidentControlRequested:
    return NoSalesIncidentControlRequested(
        event_id=EventId(engineer_wait_document_id(_MACHINE, _OPENED)),
        occurred_at=_OCCURRED,
        machine_id=_MACHINE,
        opened_event_id=_OPENED,
        action="engineer_wait",
        mute_event_id=None,
    )


def test_control_handler_repeat_mute_keeps_one_document() -> None:
    store = InMemorySalesMonitoringAuditStore()
    clearer = _RecordingClearer()
    handler = NoSalesIncidentControlHandler(audit_store=store, no_sales_clearer=clearer)
    event = _mute_requested()
    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))
    assert list(store._documents) == [event.event_id.value]
    assert clearer.calls == [MachineId("501"), MachineId("501")]


def test_control_handler_engineer_wait_clears_visit() -> None:
    store = InMemorySalesMonitoringAuditStore()
    clearer = _RecordingClearer()
    handler = NoSalesIncidentControlHandler(audit_store=store, no_sales_clearer=clearer)
    event = _engineer_requested()
    asyncio.run(handler.process(event))
    assert clearer.calls == [MachineId("501")]
    assert store._documents[event.event_id.value]["kind"] == "no_sales_engineer_wait"


def test_control_event_round_trip() -> None:
    event = _mute_requested()
    restored = sales_monitoring_event_from_document(
        sales_monitoring_event_to_document(event, aggregate_version=0)
    )
    assert restored == event
