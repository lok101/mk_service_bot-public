from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.handler_ids import NO_SALES_INCIDENT_CONTROL_HANDLER_ID
from src.application.sales_monitoring.no_sales_control import (
    engineer_wait_document_id,
    mute_cancel_document_id,
    mute_document_id,
)
from src.application.sales_monitoring.ports import DomainEventPublisher, OutboxHandlerDrainer
from src.application.sales_monitoring.run_offline_poll import drain_handler_until_empty
from src.application.service_visits import ClearNoSalesIncident
from src.domain.events import DomainEvent
from src.domain.ids import EventId, MachineId
from src.domain.sales_monitoring.control_event import (
    NoSalesIncidentControlAction,
    NoSalesIncidentControlRequested,
)

_KIND_BY_ACTION: dict[NoSalesIncidentControlAction, str] = {
    "mute": "no_sales_mute",
    "mute_cancel": "no_sales_mute_cancel",
    "engineer_wait": "no_sales_engineer_wait",
}


@runtime_checkable
class NoSalesControlWriter(Protocol):
    def upsert_control(self, document: dict[str, object]) -> None: ...


@runtime_checkable
class _ClearsNoSalesIncident(Protocol):
    def execute(self, *, machine_id: MachineId, now: datetime) -> None: ...


@beartype
def _control_event_id(
    *,
    machine_id: MachineId,
    opened_event_id: str,
    action: NoSalesIncidentControlAction,
) -> str:
    if action == "mute":
        return mute_document_id(machine_id, opened_event_id)
    if action == "engineer_wait":
        return engineer_wait_document_id(machine_id, opened_event_id)
    return mute_cancel_document_id(
        machine_id,
        mute_document_id(machine_id, opened_event_id),
    )


@beartype
def enqueue_no_sales_incident_control(
    *,
    publisher: DomainEventPublisher,
    drainer: OutboxHandlerDrainer,
    machine_id: MachineId,
    opened_event_id: str,
    action: NoSalesIncidentControlAction,
    occurred_at: datetime | None = None,
    mute_event_id: str | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else datetime.now(tz=UTC)
    event_id_value = _control_event_id(
        machine_id=machine_id,
        opened_event_id=opened_event_id,
        action=action,
    )
    resolved_mute_event_id = mute_event_id
    if action == "mute_cancel" and resolved_mute_event_id is None:
        resolved_mute_event_id = mute_document_id(machine_id, opened_event_id)
    publisher.publish(
        NoSalesIncidentControlRequested(
            event_id=EventId(event_id_value),
            occurred_at=now,
            machine_id=machine_id,
            opened_event_id=opened_event_id,
            action=action,
            mute_event_id=resolved_mute_event_id,
        ),
    )
    drain_handler_until_empty(drainer, NO_SALES_INCIDENT_CONTROL_HANDLER_ID)


@beartype
@dataclass(frozen=True, slots=True)
class NoSalesIncidentControlHandler:
    audit_store: NoSalesControlWriter
    no_sales_clearer: ClearNoSalesIncident | _ClearsNoSalesIncident

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, NoSalesIncidentControlRequested):
            raise NonRetryableOutboxError(
                f"Unsupported event: {type(event).__name__}",
            )
        kind = _KIND_BY_ACTION[event.action]
        self.audit_store.upsert_control(
            {
                "_id": event.event_id.value,
                "kind": kind,
                "machine_id": event.machine_id.value,
                "opened_event_id": event.opened_event_id,
                "mute_event_id": event.mute_event_id,
            }
        )
        if event.action != "mute_cancel":
            self.no_sales_clearer.execute(
                machine_id=event.machine_id,
                now=event.occurred_at,
            )
