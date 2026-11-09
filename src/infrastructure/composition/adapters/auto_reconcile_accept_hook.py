from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import FormSubmissionRejectedError
from src.application.machine_operations.ports import DomainEventPublisher, OutboxStore
from src.application.technician_settlement import enqueue_portion_sync_transfers
from src.application.technician_warehouse.ports import TechnicianWarehouseRepository
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class AcceptTechnicianWarehouseInventoryPort(Protocol):
    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted: ...


@beartype
@dataclass(frozen=True, slots=True)
class AcceptWithAutoReconcileEnqueue:
    """Composition guard: portion lock before accept; enqueue sync after success."""

    inner: AcceptTechnicianWarehouseInventoryPort
    outbox_store: OutboxStore
    publisher: DomainEventPublisher
    auto_reconcile_enabled: bool
    warehouse_repository: TechnicianWarehouseRepository

    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted:
        tech = token_payload.technician_id
        if self.auto_reconcile_enabled:
            active = self.outbox_store.find_active_portion_event_id(tech.value)
            if active is not None:
                _LOGGER.warning(
                    "portion_lock_reject technician_id=%s active_event_id=%s",
                    tech.value,
                    active,
                )
                raise FormSubmissionRejectedError(
                    f"active settlement portion in progress: {active}",
                )
        event = self.inner.execute(
            form_id=form_id,
            submitted_at=submitted_at,
            form_token=form_token,
            token_payload=token_payload,
            answers=answers,
        )
        if self.auto_reconcile_enabled and event.baseline is False:
            warehouse = self.warehouse_repository.get(event.technician_id)
            if warehouse.is_closed():
                _LOGGER.info(
                    "auto_reconcile_skip_enqueue warehouse_closed technician_id=%s",
                    event.technician_id.value,
                )
            else:
                enqueue_portion_sync_transfers(event=event, publisher=self.publisher)
        return event
