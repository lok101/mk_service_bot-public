from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.application.technician_settlement.draft import ReconciliationDraft
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.finalize_reconciliation import (
    FinalizeTechnicianReconciliation,
)
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    ImportedTransferRef,
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportResult,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement import (
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-a")
_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)
_INVENTORY_ID = "warehouse-inv-2"
_SESSION_EVENT_TYPES = (
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)


@dataclass
class _NoOpImporter:
    transfer_refs: tuple[ImportedTransferRef, ...] = ()

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        _ = technician_id, anchor_at
        return TechnicianWarehouseImportResult(
            imported=0,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=self.transfer_refs,
            unmatched_products=(),
        )


@dataclass
class _WarehouseDeltaPort:
    delta: TechnicianWarehouseDelta | None = None
    calls: list[tuple[TechnicianId, datetime | None, datetime]] = field(default_factory=list)

    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None:
        _ = skip_import
        self.calls.append((technician_id, after, until))
        return self.delta


class _ResidualRepo:
    def __init__(self) -> None:
        self.saved: list[object] = []

    def save(self, document: object) -> None:
        self.saved.append(document)

    def count_all(self) -> int:
        return len(self.saved)

    def delete_all(self) -> int:
        count = len(self.saved)
        self.saved.clear()
        return count


@dataclass
class _WarehouseRepo:
    inventory_id: str = _INVENTORY_ID
    closed: bool = False

    def get(self, technician_id: TechnicianId):
        from types import SimpleNamespace

        _ = technician_id
        warehouse = MagicMock()
        warehouse.is_closed.return_value = self.closed
        warehouse.latest_inventory_id = self.inventory_id
        warehouse.compute_warehouse_delta_between_latest_inventories.return_value = SimpleNamespace(
            current_inventory_id=self.inventory_id,
            current_inventory_moment=_ANCHOR,
        )
        return warehouse

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


@dataclass
class _RecordingWarehouseFinalize:
    finalized_session_ids: list[str] = field(default_factory=list)

    def finalize_transfers(self, session_id: str) -> None:
        self.finalized_session_ids.append(session_id)


def _snap(period_id: str, day: int) -> ResponsibilityPeriodReconciliation:
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
                delta=Decimal("-1000"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
    )


def _delta() -> TechnicianWarehouseDelta:
    return TechnicianWarehouseDelta(
        warehouse_inventory_id=_INVENTORY_ID,
        inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        calculated_stock_by_sku={"coffee": Decimal("5000")},
        actual_stock_by_sku={"coffee": Decimal("6000")},
        transfer_refs=(ImportedTransferRef("move-1", "hash-1"),),
        unmatched_products=(),
        previous_actual_by_sku={"coffee": Decimal("20")},
        supply_in_by_sku={"coffee": Decimal("10")},
        returns_by_sku={},
        loadings_by_sku={},
    )


def _build_flow() -> tuple[
    PreviewTechnicianReconciliation,
    FinalizeTechnicianReconciliation,
    InMemoryReconciliationDraftStore,
    _WarehouseDeltaPort,
    InMemoryTechnicianSettlementRepository,
    _WarehouseRepo,
]:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    delta_port = _WarehouseDeltaPort(delta=_delta())
    warehouse_repo = _WarehouseRepo()
    settlement = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=settlement,
        warehouse_delta_port=delta_port,
        warehouse_repository=warehouse_repo,
        importer=_NoOpImporter(transfer_refs=(ImportedTransferRef("move-1", "hash-1"),)),
    )
    draft_store = InMemoryReconciliationDraftStore()
    preview = PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=draft_store,
    )
    finalize = FinalizeTechnicianReconciliation(
        draft_store=draft_store,
        warehouse_repository=warehouse_repo,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement),
        settlement_repository=settlement,
        reconciliation_repo=period_repo,
        residual_repo=_ResidualRepo(),
        warehouse_finalize=_RecordingWarehouseFinalize(),
    )
    return preview, finalize, draft_store, delta_port, settlement, warehouse_repo


def test_preview_upserts_draft_finalize_applies_without_import() -> None:
    preview, finalize, draft_store, delta_port, settlement, _warehouse = _build_flow()

    preview_result = preview.execute(technician_id=_TECHNICIAN_ID)
    assert preview_result.can_finalize is True
    draft = draft_store.get(_TECHNICIAN_ID.value, "inventory")
    assert draft is not None
    assert draft.kind == "inventory"
    assert draft.warehouse_inventory_id == _INVENTORY_ID
    assert draft.anchor_at == _ANCHOR
    import_calls_after_preview = len(delta_port.calls)

    result = finalize.execute(technician_id=_TECHNICIAN_ID)
    assert len(delta_port.calls) == import_calls_after_preview
    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is None
    assert sum(1 for event in settlement.events if isinstance(event, _SESSION_EVENT_TYPES)) == 1
    assert result.warehouse_inventory_id == _INVENTORY_ID


def test_finalize_blocked_when_draft_stale_after_new_inventory() -> None:
    preview, finalize, draft_store, _delta_port, settlement, warehouse = _build_flow()
    preview.execute(technician_id=_TECHNICIAN_ID)
    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is not None
    warehouse.inventory_id = "warehouse-inv-3"

    with pytest.raises(ReconciliationBlocked, match="draft stale"):
        finalize.execute(technician_id=_TECHNICIAN_ID)

    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is not None
    assert sum(1 for event in settlement.events if isinstance(event, _SESSION_EVENT_TYPES)) == 0


def test_finalize_blocked_on_draft_kind_mismatch() -> None:
    _preview, finalize, draft_store, _delta_port, settlement, _warehouse = _build_flow()
    draft_store.upsert(
        ReconciliationDraft(
            technician_id=_TECHNICIAN_ID.value,
            kind="exit",
            warehouse_inventory_id="exit-1",
            warehouse_inventory_moment=_ANCHOR,
            plan={"mode": "exit_warehouse_closed", "period_ids": []},
            updated_at=_ANCHOR,
            anchor_at=None,
        )
    )

    with pytest.raises(ReconciliationBlocked, match="draft kind mismatch"):
        finalize.execute(technician_id=_TECHNICIAN_ID)

    assert sum(1 for event in settlement.events if isinstance(event, _SESSION_EVENT_TYPES)) == 0


def test_finalize_blocked_when_warehouse_closed() -> None:
    preview, finalize, draft_store, _delta_port, settlement, warehouse = _build_flow()
    preview.execute(technician_id=_TECHNICIAN_ID)
    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is not None
    warehouse.closed = True

    with pytest.raises(ReconciliationBlocked, match="warehouse is closed; use exit-reconcile"):
        finalize.execute(technician_id=_TECHNICIAN_ID)

    assert draft_store.get(_TECHNICIAN_ID.value, "inventory") is not None
    assert sum(1 for event in settlement.events if isinstance(event, _SESSION_EVENT_TYPES)) == 0


def test_exit_preview_reads_latest_delta_and_upserts_exit_draft() -> None:
    from src.application.technician_settlement.exit_reconciliation import (
        FinalizeExitTechnicianReconciliation,
        PreviewExitTechnicianReconciliation,
    )
    from src.application.technician_settlement.list_technician_reconciliation_blockers import (
        ListTechnicianReconciliationBlockersResult,
    )
    from src.domain.technician_warehouse.models import TechnicianWarehouseDelta as DomainDelta

    tech = TechnicianId("tech-exit")
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="p-exit",
            machine_id=MachineId("vm-01"),
            responsible_technician_id=tech,
            opening_revision_id=RevisionId("r1"),
            closing_revision_id=RevisionId("r2"),
            opened_at=datetime(2026, 5, 1, tzinfo=UTC),
            closed_at=datetime(2026, 5, 10, tzinfo=UTC),
            lines=(
                ReconciliationLine(
                    product_code="coffee",
                    actual_prev=Decimal("0"),
                    actual=Decimal("0"),
                    calculated=Decimal("0"),
                    delta=Decimal("-1"),
                ),
            ),
            sales_lines=(),
            load_count=0,
            status="complete",
            ledger_posted=True,
        )
    )
    delta = DomainDelta(
        current_inventory_id="exit-evt-1",
        current_inventory_moment=now,
        previous_inventory_id="inv-b",
        previous_inventory_moment=datetime(2026, 7, 1, tzinfo=UTC),
        actual_by_sku={},
        calculated_by_sku={"coffee": Decimal("1")},
        delta_by_sku={"coffee": Decimal("-1")},
        transfer_document_ids=("ret-1",),
        transfer_content_hashes=("hash-ret",),
        previous_actual_by_sku={"coffee": Decimal("10")},
        supply_in_by_sku={},
        returns_by_sku={"coffee": Decimal("10")},
        loadings_by_sku={},
    )
    warehouse = MagicMock()
    warehouse.is_closed.return_value = True
    warehouse.latest_warehouse_delta.return_value = delta

    @dataclass
    class _WarehouseRepoExit:
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

    class _Blockers:
        def execute(
            self,
            technician_id: TechnicianId,
            *,
            checked_at: datetime | None = None,
        ) -> ListTechnicianReconciliationBlockersResult:
            _ = checked_at
            return ListTechnicianReconciliationBlockersResult(
                technician_id=technician_id,
                technician_name="Tech",
                pending_sales=(),
                operational_open=(),
            )

    draft_store = InMemoryReconciliationDraftStore()
    settlement = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    warehouse_repo = _WarehouseRepoExit(warehouse=warehouse)
    preview = PreviewExitTechnicianReconciliation(
        warehouse_repository=warehouse_repo,
        reconciliation_repo=period_repo,
        blockers=_Blockers(),
        draft_store=draft_store,
    )
    preview.build_preview(technician_id=tech)
    warehouse.latest_warehouse_delta.assert_called()
    draft = draft_store.get(tech.value, "exit")
    assert draft is not None
    assert draft.kind == "exit"
    assert draft.warehouse_inventory_id == "exit-evt-1"
    assert draft.anchor_at is None

    finalize = FinalizeExitTechnicianReconciliation(
        warehouse_repository=warehouse_repo,
        reconciliation_repo=period_repo,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement),
        settlement_repository=settlement,
        residual_repo=_ResidualRepo(),
        warehouse_finalize=_RecordingWarehouseFinalize(),
        draft_store=draft_store,
    )
    result = finalize.execute(technician_id=tech)
    assert result.mode == "exit_warehouse_closed"
    assert draft_store.get(tech.value, "exit") is None
    assert sum(1 for event in settlement.events if isinstance(event, _SESSION_EVENT_TYPES)) == 1
