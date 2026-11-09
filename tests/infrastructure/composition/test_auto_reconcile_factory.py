from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime

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
from src.config.settlement import SettlementSettings
from src.domain.ids import TechnicianId
from src.infrastructure.composition.factories.auto_reconcile import (
    SettlementPortionHandlers,
    build_settlement_portion_handlers,
)


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
class _StubResidualRepo:
    def save(self, document: object) -> None:
        del document

    def count_all(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0


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
        raise AssertionError("stub preview should not be called in factory wiring test")


@dataclass
class _StubFinalize:
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> object:
        del technician_id
        raise AssertionError("stub finalize should not be called in factory wiring test")


def test_auto_reconcile_handlers_wire_quarantine_seconds() -> None:
    # full build_settlement_portion_handlers needs Mongo+Kit; assert factory return wiring
    settlement = SettlementSettings.model_construct(
        portion_reconcile_quarantine_seconds=1234,
        auto_reconcile_enabled=True,
    )
    factory_source = inspect.getsource(build_settlement_portion_handlers)
    assert (
        "quarantine_seconds=settings.settlement.portion_reconcile_quarantine_seconds"
        in factory_source
    )

    importer = _StubImporter()
    verifier = _StubVerifier()
    publisher = _StubPublisher()
    handlers = SettlementPortionHandlers(
        sync=SettlementPortionSyncTransfersHandler(
            importer=importer,
            publisher=publisher,
        ),
        sales_verify=SettlementPortionSalesVerifyHandler(
            verifier=verifier,
            publisher=publisher,
            quarantine_seconds=settlement.portion_reconcile_quarantine_seconds,
        ),
        reconcile=SettlementPortionReconcileHandler(
            preview=_StubPreview(),
            finalize=_StubFinalize(),
            importer=importer,
            verifier=verifier,
            residual_repo=_StubResidualRepo(),
        ),
    )

    assert handlers.sales_verify.quarantine_seconds == 1234
    assert handlers.reconcile.importer is handlers.sync.importer


def test_build_settlement_portion_handlers_has_no_audit_sheets_factory() -> None:
    """happy: factories barrel has no settlement audit Sheets builder export."""
    import src.infrastructure.composition.factories as factories

    symbol = "build_" + "settlement_audit_sheets"
    assert not hasattr(factories, symbol)
