from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.outbox.handler_ids import SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID
from src.application.outbox.settlement_portion_sync_transfers import PortionEventPublisher
from src.application.technician_settlement import enqueue_portion_reconcile
from src.domain.events import DomainEvent
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.portion_events import SettlementPortionSalesVerifyRequested

_LOGGER = logging.getLogger(__name__)


def _is_retryable_kit_failure(exc: BaseException) -> bool:
    if type(exc).__name__ == "KitVendingNetworkError":
        return True
    return getattr(exc, "result_code", None) == 1


@runtime_checkable
class PortionSalesVerifier(Protocol):
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> object: ...


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionSalesVerifyHandler:
    verifier: PortionSalesVerifier
    publisher: PortionEventPublisher
    quarantine_seconds: int = 0

    @beartype
    async def process(self, event: DomainEvent) -> None:
        if not isinstance(event, SettlementPortionSalesVerifyRequested):
            raise NonRetryableOutboxError(
                f"Unsupported settlement portion sales verify event: {type(event).__name__}",
            )
        try:
            result = self.verifier.execute(
                technician_id=event.technician_id,
                cutoff=event.warehouse_inventory_moment,
            )
        except Exception as exc:
            if _is_retryable_kit_failure(exc):
                raise DeferredRetryOutboxError(
                    str(exc),
                    delay=timedelta(seconds=60),
                ) from exc
            raise
        _LOGGER.info(
            "settlement_portion_sales_verify_completed technician_id=%s "
            "warehouse_inventory_id=%s result=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
            result,
        )
        not_before = (
            datetime.now(tz=UTC) + timedelta(seconds=self.quarantine_seconds)
            if self.quarantine_seconds > 0
            else None
        )
        _LOGGER.info(
            "settlement_portion_reconcile_enqueued technician_id=%s "
            "warehouse_inventory_id=%s not_before=%s",
            event.technician_id.value,
            event.warehouse_inventory_id,
            not_before.isoformat() if not_before is not None else None,
        )
        enqueue_portion_reconcile(
            publisher=self.publisher,
            technician_id=event.technician_id,
            warehouse_inventory_id=event.warehouse_inventory_id,
            warehouse_inventory_moment=event.warehouse_inventory_moment,
            not_before=not_before,
        )


__all__ = [
    "SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID",
    "SettlementPortionSalesVerifyHandler",
]
