from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.outbox.handler_ids import (
    SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
)
from src.application.outbox.settlement_portion_reconcile import (
    SettlementPortionReconcileHandler,
)
from src.application.outbox.settlement_portion_sales_verify import (
    SettlementPortionSalesVerifyHandler,
)
from src.application.outbox.settlement_portion_sync_transfers import (
    SettlementPortionSyncTransfersHandler,
)
from src.application.technician_settlement import ReconciliationPreview
from src.application.technician_warehouse import TechnicianWarehouseImportResult
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


@dataclass
class _StubImporter:
    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult:
        del technician_id, anchor_at
        return TechnicianWarehouseImportResult(
            imported=0,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=(),
            unmatched_products=(),
        )


@dataclass
class _StubPublisher:
    def publish(self, event: object) -> None:
        del event


@dataclass
class _StubVerifier:
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> object:
        del technician_id, cutoff
        return object()


@dataclass
class _StubPreview:
    def build_preview_for_inventory(
        self,
        *,
        technician_id: TechnicianId,
        warehouse_inventory_id: str,
        skip_import: bool = True,
    ) -> ReconciliationPreview:
        del technician_id, warehouse_inventory_id, skip_import
        raise AssertionError("stub preview should not be called in wiring test")


@dataclass
class _StubFinalize:
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> object:
        del technician_id
        raise AssertionError("stub finalize should not be called in wiring test")


def _stub_sync_handler() -> SettlementPortionSyncTransfersHandler:
    return SettlementPortionSyncTransfersHandler(
        importer=_StubImporter(),
        publisher=_StubPublisher(),
    )


def _stub_sales_handler() -> SettlementPortionSalesVerifyHandler:
    return SettlementPortionSalesVerifyHandler(
        verifier=_StubVerifier(),
        publisher=_StubPublisher(),
    )


class _StubResidualRepo:
    def save(self, document: object) -> None:
        _ = document

    def count_all(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0


def _stub_reconcile_handler() -> SettlementPortionReconcileHandler:
    return SettlementPortionReconcileHandler(
        preview=_StubPreview(),
        finalize=_StubFinalize(),
        importer=_StubImporter(),
        verifier=_StubVerifier(),
        residual_repo=_StubResidualRepo(),
    )


def test_portion_handlers_registered_when_enabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        settlement_portion_sync_handler=_stub_sync_handler(),
        settlement_portion_sales_verify_handler=_stub_sales_handler(),
        settlement_portion_reconcile_handler=_stub_reconcile_handler(),
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    assert processors.is_registered(SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID)
    assert processors.is_registered(SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID)
    assert processors.is_registered(SETTLEMENT_PORTION_RECONCILE_HANDLER_ID)
    assert SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID not in publisher.handler_ids_for(
        SettlementPortionSyncTransfersRequested,
    )
    assert SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID in publisher.handler_ids_for(
        SettlementPortionSalesVerifyRequested,
    )
    assert SETTLEMENT_PORTION_RECONCILE_HANDLER_ID in publisher.handler_ids_for(
        SettlementPortionReconcileRequested,
    )

    ingress_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_outbox_handlers(
        publisher=ingress_publisher,
        processors=OutboxProcessorRegistry(),
        deps=deps,
        process="ingress",
    )
    assert SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID in ingress_publisher.handler_ids_for(
        SettlementPortionSyncTransfersRequested,
    )


def test_auto_reconcile_handlers_not_registered_when_disabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        settlement_portion_sync_handler=None,
        settlement_portion_sales_verify_handler=None,
        settlement_portion_reconcile_handler=None,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )

    assert processors.is_registered(SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID) is False
    assert processors.is_registered(SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID) is False
    assert processors.is_registered(SETTLEMENT_PORTION_RECONCILE_HANDLER_ID) is False
    assert SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID not in publisher.handler_ids_for(
        SettlementPortionSyncTransfersRequested,
    )
    assert SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID not in publisher.handler_ids_for(
        SettlementPortionSalesVerifyRequested,
    )
    assert SETTLEMENT_PORTION_RECONCILE_HANDLER_ID not in publisher.handler_ids_for(
        SettlementPortionReconcileRequested,
    )
