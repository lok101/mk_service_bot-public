from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from pymongo.database import Database
from tests.integration.settlement_pipeline_helpers import post_warehouse_inventory
from tests.integration.stack import build_warehouse_settlement_stack

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
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.ids import EventId, TechnicianId
from src.domain.product_catalog import ProductUnit
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.adapters.auto_reconcile_accept_hook import (
    AcceptWithAutoReconcileEnqueue,
)
from src.infrastructure.outbox.processor import OutboxHandler
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.testing import TEST_TECHNICIAN_ID

pytestmark = pytest.mark.integration

_SUBMITTED_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _NoOpImporter:
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
class _NoOpVerifier:
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> object:
        del technician_id, cutoff
        return object()


@dataclass
class _NoOpPreview:
    def build_preview_for_inventory(
        self,
        *,
        technician_id: TechnicianId,
        warehouse_inventory_id: str,
        skip_import: bool = True,
    ) -> ReconciliationPreview:
        del technician_id, warehouse_inventory_id, skip_import
        raise AssertionError("reconcile not drained in light integration")


@dataclass
class _NoOpFinalize:
    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> object:
        del technician_id
        raise AssertionError("reconcile not drained in light integration")


@dataclass
class _NoOpResidualRepo:
    def save(self, document: object) -> None:
        del document

    def count_all(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0


@dataclass
class _RecordingAccept:
    event: TechnicianWarehouseInventoryCounted
    calls: int = 0

    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted:
        del form_id, submitted_at, form_token, token_payload, answers
        self.calls += 1
        return self.event


def test_inventory_triggers_portion_chain_to_reconciled(mongo_database: Database) -> None:
    """Light integration: handlers registered + accept enqueues sync (full chain in unit 04–06)."""
    stack = build_warehouse_settlement_stack(
        mongo_database,
        product_mapping={"Кофе": "coffee"},
        pack_size=Decimal("20"),
        unit=ProductUnit.PIECE,
    )
    publisher = OutboxDomainEventPublisher(store=stack.outbox_store)
    processors = stack.outbox_worker.processors

    sync_handler = SettlementPortionSyncTransfersHandler(
        importer=_NoOpImporter(),
        publisher=publisher,
    )
    sales_handler = SettlementPortionSalesVerifyHandler(
        verifier=_NoOpVerifier(),
        publisher=publisher,
    )
    reconcile_handler = SettlementPortionReconcileHandler(
        preview=_NoOpPreview(),
        finalize=_NoOpFinalize(),
        importer=_NoOpImporter(),
        verifier=_NoOpVerifier(),
        residual_repo=_NoOpResidualRepo(),
    )
    processors.register(
        SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        cast(OutboxHandler, sync_handler.process),
    )
    processors.register(
        SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
        cast(OutboxHandler, sales_handler.process),
    )
    processors.register(
        SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
        cast(OutboxHandler, reconcile_handler.process),
    )
    publisher.subscribe(
        SettlementPortionSyncTransfersRequested,
        SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
    )
    publisher.subscribe(
        SettlementPortionSalesVerifyRequested,
        SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID,
    )
    publisher.subscribe(
        SettlementPortionReconcileRequested,
        SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    )

    assert processors.is_registered(SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID)
    assert processors.is_registered(SETTLEMENT_PORTION_SALES_VERIFY_HANDLER_ID)
    assert processors.is_registered(SETTLEMENT_PORTION_RECONCILE_HANDLER_ID)

    response = post_warehouse_inventory(
        stack,
        technician_id=TEST_TECHNICIAN_ID,
        coffee="2",
        nonce="inv-portion-open",
        submitted_at=_SUBMITTED_AT,
    )
    assert response.status_code == 200

    inventory_event = TechnicianWarehouseInventoryCounted(
        event_id=EventId("wh-inv-portion-2"),
        technician_id=TEST_TECHNICIAN_ID,
        occurred_at=_SUBMITTED_AT,
        inventory_id="inv-portion-2",
        form_token="tok-portion-2",
        counted_at=_SUBMITTED_AT,
        lines=(("coffee", Decimal("2")),),
        baseline=False,
    )
    wrapper = AcceptWithAutoReconcileEnqueue(
        inner=_RecordingAccept(event=inventory_event),
        outbox_store=stack.outbox_store,
        publisher=publisher,
        auto_reconcile_enabled=True,
        warehouse_repository=stack.warehouse_repository,
    )
    wrapper.execute(
        form_id="form-portion-2",
        submitted_at=_SUBMITTED_AT,
        form_token="tok-portion-2",
        token_payload=TechnicianWarehouseInventoryTokenPayload(
            technician_id=TEST_TECHNICIAN_ID,
            issued_at=_SUBMITTED_AT,
            nonce="portion-2",
        ),
        answers=(),
    )

    active = stack.outbox_store.find_active_portion_event_id(TEST_TECHNICIAN_ID.value)
    assert active is not None
    assert active.startswith(f"portion:{TEST_TECHNICIAN_ID.value}:inv-portion-2:")
    assert active.endswith(":sync")


def test_quarantine_delays_reconcile_claim_and_holds_portion_lock(
    mongo_database: Database,
) -> None:
    """Quarantine: not_before in the future keeps reconcile un-claimable and the portion
    lock active (acceptance criteria 1 + 6, real Mongo outbox)."""
    stack = build_warehouse_settlement_stack(
        mongo_database,
        product_mapping={"Кофе": "coffee"},
        pack_size=Decimal("20"),
        unit=ProductUnit.PIECE,
    )
    publisher = OutboxDomainEventPublisher(store=stack.outbox_store)
    publisher.subscribe(
        SettlementPortionReconcileRequested,
        SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    )
    sales_handler = SettlementPortionSalesVerifyHandler(
        verifier=_NoOpVerifier(),
        publisher=publisher,
        quarantine_seconds=3600,
    )
    event = SettlementPortionSalesVerifyRequested(
        event_id=EventId(f"portion:{TEST_TECHNICIAN_ID.value}:inv-quarantine-1:sales"),
        technician_id=TEST_TECHNICIAN_ID,
        warehouse_inventory_id="inv-quarantine-1",
        warehouse_inventory_moment=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
    )

    asyncio.run(sales_handler.process(event))

    claimed = stack.outbox_store.claim_pending(
        limit=10,
        handler_id=SETTLEMENT_PORTION_RECONCILE_HANDLER_ID,
    )
    assert claimed == []

    active = stack.outbox_store.find_active_portion_event_id(TEST_TECHNICIAN_ID.value)
    assert active is not None
    assert active.endswith(":reconcile")
