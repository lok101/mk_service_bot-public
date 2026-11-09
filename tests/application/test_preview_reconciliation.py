from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
    ReconciliationBlocked,
    ReconciliationPreview,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    ImportedTransferRef,
    MoySkladUnavailable,
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportResult,
    UnmatchedMsProduct,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-a")
_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)


@dataclass
class _NoOpImporter:
    transfer_refs: tuple[ImportedTransferRef, ...] = ()
    unmatched_products: tuple[UnmatchedMsProduct, ...] = ()

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
            unmatched_products=self.unmatched_products,
        )


@dataclass
class _WarehouseDeltaPort:
    delta: TechnicianWarehouseDelta | None = None
    unmatched: tuple[UnmatchedMsProduct, ...] = ()
    error: MoySkladUnavailable | None = None
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
        if self.error is not None:
            raise self.error
        if self.delta is None and not self.unmatched:
            return None
        return self.delta or TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=self.unmatched,
        )


@dataclass
class _OpenWarehouseRepo:
    has_session_inventory: bool = True

    def get(self, technician_id: TechnicianId):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        warehouse = MagicMock()
        warehouse.is_closed.return_value = False
        if self.has_session_inventory:
            warehouse.compute_warehouse_delta_between_latest_inventories.return_value = (
                SimpleNamespace(
                    current_inventory_id="warehouse-inv-2",
                    current_inventory_moment=_ANCHOR,
                )
            )
        else:
            warehouse.compute_warehouse_delta_between_latest_inventories.return_value = None
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


def _snap(
    period_id: str, day: int, delta: Decimal = Decimal("-1000"), **kwargs
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
        status=kwargs.get("status", "complete"),
        ledger_posted=kwargs.get("ledger_posted", True),
    )


def _regular_plan() -> ReconciliationSessionPlanner:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    return ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(
            delta=TechnicianWarehouseDelta(
                warehouse_inventory_id="warehouse-inv-2",
                inventory_moment=_ANCHOR,
                warehouse_delta_by_sku={"coffee": Decimal("-2")},
                calculated_stock_by_sku={"coffee": Decimal("23")},
                actual_stock_by_sku={"coffee": Decimal("21")},
                transfer_refs=(),
                unmatched_products=(),
            ),
        ),
        warehouse_repository=_OpenWarehouseRepo(),
        importer=_NoOpImporter(transfer_refs=(ImportedTransferRef("move-1", "hash-1"),)),
    )


def _plan_with_unmatched(code: str) -> ReconciliationSessionPlanner:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    return ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(
            delta=TechnicianWarehouseDelta(
                warehouse_inventory_id="warehouse-inv-2",
                inventory_moment=_ANCHOR,
                warehouse_delta_by_sku={},
                calculated_stock_by_sku={},
                actual_stock_by_sku={},
                transfer_refs=(),
                unmatched_products=(),
            ),
        ),
        warehouse_repository=_OpenWarehouseRepo(),
        importer=_NoOpImporter(
            unmatched_products=(UnmatchedMsProduct(code, code.title(), "move-unknown"),),
        ),
    )


def _preview(plan: ReconciliationSessionPlanner) -> ReconciliationPreview:
    return PreviewTechnicianReconciliation(
        planner=plan,
        draft_store=InMemoryReconciliationDraftStore(),
    ).build_preview(technician_id=_TECHNICIAN_ID)


def test_preview_execute_has_no_anchor_at_parameter() -> None:
    """happy: PreviewTechnicianReconciliation.execute без anchor_at."""
    import inspect

    params = inspect.signature(PreviewTechnicianReconciliation.execute).parameters
    assert "anchor_at" not in params


def test_preview_execute_has_no_audit_sheets_port() -> None:
    """happy: PreviewTechnicianReconciliation без audit Sheets deps."""
    fields = PreviewTechnicianReconciliation.__dataclass_fields__
    assert "audit_sheets" not in fields
    assert "machines" not in fields
    assert "catalog" not in fields
    assert "audit_timezone" not in fields


def test_preview_exposes_domain_warehouse_inventory_and_delta() -> None:
    preview = _preview(_regular_plan())
    assert preview.warehouse_inventory_id == "warehouse-inv-2"
    assert preview.warehouse_delta_by_sku == {"coffee": Decimal("-2")}
    assert preview.calculated_stock_by_sku == {"coffee": Decimal("23")}
    assert preview.actual_stock_by_sku == {"coffee": Decimal("21")}
    assert [ref.external_document_id for ref in preview.transfer_refs] == ["move-1"]


def test_preview_with_empty_unmatched_products_is_not_blocked() -> None:
    """edge: unmatched () / legacy non-empty больше не блокирует через planner."""
    preview = _preview(_regular_plan())  # unmatched empty
    assert preview.can_finalize is True
    assert list(preview.unmatched_products) == []


def test_preview_legacy_unmatched_products_visible_but_not_blocking() -> None:
    """compat: если plan всё ещё прокидывает unmatched — не блокер."""
    preview = _preview(_plan_with_unmatched("unknown"))
    assert [item.product_code for item in preview.unmatched_products] == ["unknown"]
    assert preview.can_finalize is True


def test_preview_blocks_on_pending_in_window() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="pb",
            machine_id=MachineId("vm-01"),
            responsible_technician_id=_TECHNICIAN_ID,
            opening_revision_id=RevisionId("r1"),
            closing_revision_id=RevisionId("r2"),
            opened_at=datetime(2026, 5, 1, tzinfo=UTC),
            closed_at=datetime(2026, 5, 5, tzinfo=UTC),
            lines=(),
            sales_lines=(),
            load_count=0,
            status="pending_sales",
            ledger_posted=False,
            reconciled=False,
        ),
    )
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(),
        warehouse_repository=_OpenWarehouseRepo(),
        importer=_NoOpImporter(),
    )
    with pytest.raises(ReconciliationBlocked, match="pending periods"):
        _preview(planner)


def test_preview_without_inventory_raises() -> None:
    """error: нет session inventory → ReconciliationBlocked (не DTO с blockers)."""
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(),
        warehouse_repository=_OpenWarehouseRepo(has_session_inventory=False),
        importer=_NoOpImporter(),
    )
    with pytest.raises(
        ReconciliationBlocked,
        match="no technician warehouse inventory",
    ):
        _preview(planner)
