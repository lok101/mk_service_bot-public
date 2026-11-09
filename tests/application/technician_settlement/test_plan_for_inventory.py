from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    ImportedTransferRef,
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportResult,
)
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import TechnicianWarehouseTransferObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-a")
_T_OLD = datetime(2026, 5, 10, tzinfo=UTC)
_T_NEW = datetime(2026, 5, 25, tzinfo=UTC)
_PREVIOUS_FINALIZED_AT = datetime(2026, 5, 5, tzinfo=UTC)


@dataclass
class _WarehouseDeltaPort:
    delta: TechnicianWarehouseDelta | None = None
    calls: list[tuple[TechnicianId, datetime | None, datetime, bool]] = field(default_factory=list)

    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None:
        self.calls.append((technician_id, after, until, skip_import))
        return self.delta


@dataclass
class _RecordingImporter:
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        self.calls.append((technician_id, anchor_at))
        return TechnicianWarehouseImportResult(
            imported=0,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=(ImportedTransferRef("doc-1", "hash-1"),),
            unmatched_products=(),
        )


@dataclass
class _MutatingImporter:
    """Importer that observes a supply transfer on the shared warehouse aggregate."""

    warehouse: TechnicianWarehouse
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)
    transfer_moment: datetime = field(default_factory=lambda: datetime(2026, 5, 20, tzinfo=UTC))
    quantity: Decimal = Decimal("5")
    doc_id: str = "doc-post-import"
    content_hash: str = "hash-post-import"

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        self.calls.append((technician_id, anchor_at))
        moment = self.transfer_moment
        self.warehouse.observe_transfer(
            TechnicianWarehouseTransferObserved(
                event_id=EventId(f"event-{self.doc_id}"),
                technician_id=technician_id,
                occurred_at=moment,
                external_document_id=self.doc_id,
                moment=moment,
                updated_at=moment,
                observed_at=moment,
                content_hash=self.content_hash,
                direction=TransferDirection.SUPPLY_IN,
                lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=self.quantity),),
            ),
        )
        return TechnicianWarehouseImportResult(
            imported=1,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=(ImportedTransferRef(self.doc_id, self.content_hash),),
            unmatched_products=(),
        )


@dataclass
class _WarehouseRepo:
    warehouse: object

    def get(self, technician_id: TechnicianId):
        _ = technician_id
        return self.warehouse

    def save(self, warehouse, *, expected_version: int) -> None:
        _ = warehouse, expected_version

    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool:
        _ = technician_id, session_id
        return False


def _snap(
    period_id: str,
    day: int,
    delta: Decimal = Decimal("-1000"),
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECHNICIAN_ID,
        opening_revision_id=RevisionId("r1"),
        closing_revision_id=RevisionId("r2"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, day, tzinfo=UTC),
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=delta,
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
    )


def _settlement_with_previous_session() -> InMemoryTechnicianSettlementRepository:
    from src.domain.ids import EventId, ReconciliationSessionId
    from src.domain.technician_settlement.events import TechnicianReconciliationSessionCommitted

    event_store = InMemoryTechnicianSettlementEventStore()
    event_store.append(
        TechnicianReconciliationSessionCommitted(
            event_id=EventId("prev-session"),
            session_id=ReconciliationSessionId("sess-prev"),
            technician_id=_TECHNICIAN_ID,
            mode="inventory_delta",
            anchor_at=_PREVIOUS_FINALIZED_AT,
            period_ids=("p0",),
            deferred_period_ids=(),
            warehouse_inventory_id="warehouse-inv-1",
            warehouse_inventory_moment=_PREVIOUS_FINALIZED_AT,
            warehouse_delta_by_sku={},
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=(),
            ledger_balance_before={},
            cleared_by_sku={},
            residual_by_sku={},
            finalized_at=_PREVIOUS_FINALIZED_AT,
            executed_at=_PREVIOUS_FINALIZED_AT,
            occurred_at=_PREVIOUS_FINALIZED_AT,
        ),
        expected_version=0,
    )
    return InMemoryTechnicianSettlementRepository(event_store=event_store)


def _warehouse_with_two_inventories() -> TechnicianWarehouse:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-old",
        form_token="token-old",
        counted_at=_T_OLD,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    warehouse.count_inventory(
        inventory_id="inv-new",
        form_token="token-new",
        counted_at=_T_NEW,
        actual_by_sku={"coffee": Decimal("8")},
        baseline=False,
    )
    warehouse.clear_pending_events()
    return warehouse


def _planner(
    *,
    warehouse: object,
    importer: object | None = None,
    port: _WarehouseDeltaPort | None = None,
    period_repo: InMemoryPeriodReconciliationRepository | None = None,
) -> ReconciliationSessionPlanner:
    if period_repo is None:
        period_repo = InMemoryPeriodReconciliationRepository()
        period_repo.save(_snap("p1", 8))
    return ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=_settlement_with_previous_session(),
        warehouse_delta_port=port if port is not None else _WarehouseDeltaPort(),
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        importer=importer if importer is not None else _RecordingImporter(),
    )


def test_plan_for_inventory_uses_payload_id_not_latest() -> None:
    # happy: named inv-old while latest is inv-new; skip_import → no importer
    warehouse = _warehouse_with_two_inventories()
    importer = _RecordingImporter()
    port = _WarehouseDeltaPort()
    plan = _planner(warehouse=warehouse, importer=importer, port=port).plan_for_inventory(
        _TECHNICIAN_ID,
        warehouse_inventory_id="inv-old",
        skip_import=True,
    )
    assert plan.warehouse_inventory_id == "inv-old"
    assert plan.anchor_at == _T_OLD
    assert importer.calls == []
    assert port.calls == []


def test_plan_for_inventory_missing_id_fail_closed() -> None:
    # error: missing inventory_id → ReconciliationBlocked
    warehouse = _warehouse_with_two_inventories()
    with pytest.raises(
        ReconciliationBlocked,
        match="no technician warehouse inventory in window",
    ):
        _planner(warehouse=warehouse).plan_for_inventory(
            _TECHNICIAN_ID,
            warehouse_inventory_id="missing",
            skip_import=True,
        )


def test_plan_for_inventory_skip_import_false_uses_post_import_delta() -> None:
    # happy: importer mutates warehouse; plan must use post-import delta for named inventory
    warehouse = _warehouse_with_two_inventories()
    pre_import = warehouse.compute_warehouse_delta_for_inventory_id("inv-new")
    assert pre_import is not None
    assert pre_import.supply_in_by_sku == {}
    assert pre_import.delta_by_sku["coffee"] == Decimal("-2")

    importer = _MutatingImporter(warehouse=warehouse)
    plan = _planner(warehouse=warehouse, importer=importer).plan_for_inventory(
        _TECHNICIAN_ID,
        warehouse_inventory_id="inv-new",
        skip_import=False,
    )

    assert importer.calls == [(_TECHNICIAN_ID, _T_NEW)]
    assert plan.warehouse_inventory_id == "inv-new"
    assert plan.supply_in_by_sku == {"coffee": Decimal("5")}
    assert plan.warehouse_delta_by_sku == {"coffee": Decimal("-7")}
    assert plan.transfer_refs == (ImportedTransferRef("doc-post-import", "hash-post-import"),)
