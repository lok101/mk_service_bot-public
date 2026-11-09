from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

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
    UnmatchedMsProduct,
)
from src.domain.ids import EventId, MachineId, ReconciliationSessionId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement import (
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)
from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-a")
_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)
_INVENTORY_ID = "warehouse-inv-2"


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
        if self.delta is None and not self.unmatched:
            return None
        return self.delta or TechnicianWarehouseDelta(
            warehouse_inventory_id=_INVENTORY_ID,
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=self.unmatched,
        )


@dataclass
class _RecordingWarehouseFinalize:
    finalized_session_ids: list[str] = field(default_factory=list)
    import_calls: int = 0

    def finalize_transfers(self, session_id: str) -> None:
        self.finalized_session_ids.append(session_id)


class _ResidualRepo:
    def __init__(self) -> None:
        self.saved: list[ReconciliationResidualDocument] = []

    def save(self, document: ReconciliationResidualDocument) -> None:
        self.saved.append(document)

    def count_all(self) -> int:
        return len(self.saved)

    def delete_all(self) -> int:
        count = len(self.saved)
        self.saved.clear()
        return count


@dataclass
class _OpenWarehouseRepo:
    def get(self, technician_id: TechnicianId):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        warehouse = MagicMock()
        warehouse.is_closed.return_value = False
        warehouse.latest_inventory_id = _INVENTORY_ID
        warehouse.compute_warehouse_delta_between_latest_inventories.return_value = SimpleNamespace(
            current_inventory_id=_INVENTORY_ID,
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


def _snap(
    period_id: str, day: int, delta: Decimal = Decimal("-1000")
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
                warehouse_inventory_id=_INVENTORY_ID,
                inventory_moment=_ANCHOR,
                warehouse_delta_by_sku={"coffee": Decimal("1000")},
                calculated_stock_by_sku={"coffee": Decimal("5000")},
                actual_stock_by_sku={"coffee": Decimal("6000")},
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
                warehouse_inventory_id=_INVENTORY_ID,
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


def _plan_without_warehouse_inventory() -> ReconciliationSessionPlanner:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    return ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(),
        warehouse_repository=_OpenWarehouseRepo(),
        importer=_NoOpImporter(),
    )


def _finalize_case(
    plan: ReconciliationSessionPlanner,
    *,
    warehouse: _RecordingWarehouseFinalize | None = None,
    run_preview: bool = True,
    residual_repo: _ResidualRepo | None = None,
) -> tuple[
    FinalizeTechnicianReconciliation,
    InMemoryTechnicianSettlementRepository,
    _RecordingWarehouseFinalize,
    PreviewTechnicianReconciliation,
    _ResidualRepo,
]:
    event_store = InMemoryTechnicianSettlementEventStore()
    settlement = InMemoryTechnicianSettlementRepository(event_store=event_store)
    period_repo = plan.reconciliation_repo
    warehouse_finalize = warehouse or _RecordingWarehouseFinalize()
    draft_store = InMemoryReconciliationDraftStore()
    residuals = residual_repo or _ResidualRepo()
    preview = PreviewTechnicianReconciliation(
        planner=plan,
        draft_store=draft_store,
    )
    service = FinalizeTechnicianReconciliation(
        draft_store=draft_store,
        warehouse_repository=plan.warehouse_repository,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement),
        settlement_repository=settlement,
        reconciliation_repo=period_repo,
        residual_repo=residuals,
        warehouse_finalize=warehouse_finalize,
    )
    if run_preview:
        preview.execute(technician_id=_TECHNICIAN_ID)
    return service, settlement, warehouse_finalize, preview, residuals


def _session_count(settlement: InMemoryTechnicianSettlementRepository) -> int:
    return sum(
        1
        for event in settlement.events
        if isinstance(
            event,
            (TechnicianReconciliationSessionCommitted, TechnicianReconciliationSessionCompleted),
        )
    )


def test_finalize_execute_has_no_write_audit_parameter() -> None:
    """happy: FinalizeTechnicianReconciliation без audit Sheets deps и write_audit."""
    fields = FinalizeTechnicianReconciliation.__dataclass_fields__
    assert "audit_sheets" not in fields
    assert "machines" not in fields
    assert "catalog" not in fields
    assert "audit_timezone" not in fields
    params = inspect.signature(FinalizeTechnicianReconciliation.execute).parameters
    assert "write_audit" not in params


def test_finalize_idempotent_on_legacy_iso_session_id() -> None:
    """idempotency: completion под legacy {tech}:{anchor.isoformat()} → no-op re-apply."""
    service, settlement, warehouse, preview_uc, _residual = _finalize_case(
        _regular_plan(),
        run_preview=False,
    )
    preview = preview_uc.execute(technician_id=_TECHNICIAN_ID)
    legacy = ReconciliationSessionId(
        f"{_TECHNICIAN_ID.value}:{preview.anchor_at.isoformat()}",
    )
    settlement.event_store.append(
        TechnicianReconciliationSessionCompleted(
            event_id=EventId("legacy-done"),
            session_id=legacy,
            technician_id=_TECHNICIAN_ID,
            mode="inventory_delta",
            anchor_at=preview.anchor_at,
            period_ids=tuple(p.period_id for p in preview.scope),
            deferred_period_ids=(),
            warehouse_inventory_id=preview.warehouse_inventory_id or _INVENTORY_ID,
            warehouse_inventory_moment=preview.warehouse_inventory_moment or preview.anchor_at,
            warehouse_delta_by_sku=dict(preview.warehouse_delta_by_sku),
            warehouse_source="domain_technician_warehouse",
            warehouse_transfer_refs=(),
            ledger_balance_before={},
            residual_by_sku={},
            finalized_at=preview.anchor_at,
            occurred_at=preview.anchor_at,
            executed_at=preview.anchor_at,
        ),
        expected_version=0,
    )
    settlement.event_store.append(
        TechnicianLedgerClearedByReconciliation(
            event_id=EventId("legacy-cleared"),
            session_id=legacy,
            technician_id=_TECHNICIAN_ID,
            period_ids=tuple(p.period_id for p in preview.scope),
            cleared_by_sku={},
            residual_by_sku={},
            occurred_at=preview.anchor_at,
        ),
        expected_version=1,
    )
    result = service.execute(technician_id=_TECHNICIAN_ID)
    assert result.session_id.value == legacy.value
    assert warehouse.finalized_session_ids == [legacy.value]
    new_id = f"{_TECHNICIAN_ID.value}:{_INVENTORY_ID}"
    assert (
        settlement.get(_TECHNICIAN_ID).completion_result_for(
            ReconciliationSessionId(new_id),
        )
        is None
    )
    assert _session_count(settlement) == 1


def test_finalize_session_id_uses_warehouse_inventory_id() -> None:
    """happy: session_id = {technician_id}:{warehouse_inventory_id}."""
    service, _settlement, warehouse, _preview, _residual = _finalize_case(_regular_plan())
    result = service.execute(technician_id=_TECHNICIAN_ID)
    expected = f"{_TECHNICIAN_ID.value}:{_INVENTORY_ID}"
    assert result.session_id.value == expected
    assert warehouse.finalized_session_ids == [expected]


def test_finalize_persists_neutral_warehouse_fields_and_marks_transfers_finalized() -> None:
    service, settlement, warehouse, _preview, _residual = _finalize_case(_regular_plan())
    result = service.execute(technician_id=_TECHNICIAN_ID)
    assert result.warehouse_inventory_id == _INVENTORY_ID
    assert result.warehouse_source == "domain_technician_warehouse"
    assert warehouse.finalized_session_ids == [result.session_id.value]
    assert _session_count(settlement) == 1


def test_finalize_succeeds_when_warehouse_unmatched_products_empty_legacy_shape() -> None:
    """happy: unmatched в delta не мешает finalize (после planner fix)."""
    service, settlement, _warehouse, _preview, _residual = _finalize_case(
        _plan_with_unmatched("unknown"),
    )
    result = service.execute(technician_id=_TECHNICIAN_ID)
    assert _session_count(settlement) == 1
    assert result.session_id is not None


def test_finalize_does_not_write_session_when_warehouse_blocked() -> None:
    service, settlement, _warehouse, preview, _residual = _finalize_case(
        _plan_without_warehouse_inventory(),
        run_preview=False,
    )
    assert (
        preview.build_preview(
            technician_id=_TECHNICIAN_ID,
        ).can_finalize
        is False
    )
    with pytest.raises(ReconciliationBlocked, match="no reconciliation draft"):
        service.execute(technician_id=_TECHNICIAN_ID)
    assert _session_count(settlement) == 0


@dataclass
class _FailingOnceWarehouseFinalize(_RecordingWarehouseFinalize):
    should_fail: bool = True

    def finalize_transfers(self, session_id: str) -> None:
        if self.should_fail:
            self.should_fail = False
            raise RuntimeError("warehouse finalize failed")
        super().finalize_transfers(session_id)


def test_finalize_retry_after_warehouse_finalize_failure_is_idempotent() -> None:
    service, settlement, warehouse, _preview, _residual = _finalize_case(
        _regular_plan(),
        warehouse=_FailingOnceWarehouseFinalize(),
    )
    with pytest.raises(RuntimeError, match="warehouse finalize failed"):
        service.execute(technician_id=_TECHNICIAN_ID)
    assert _session_count(settlement) == 1

    result = service.execute(technician_id=_TECHNICIAN_ID)
    assert _session_count(settlement) == 1
    assert warehouse.finalized_session_ids == [result.session_id.value]


def test_finalize_creates_residual_when_non_zero() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10, Decimal("-1000")))
    plan = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(
            delta=TechnicianWarehouseDelta(
                warehouse_inventory_id=_INVENTORY_ID,
                inventory_moment=_ANCHOR,
                warehouse_delta_by_sku={"coffee": Decimal("950")},
                calculated_stock_by_sku={},
                actual_stock_by_sku={},
                transfer_refs=(),
                unmatched_products=(),
            ),
        ),
        warehouse_repository=_OpenWarehouseRepo(),
        importer=_NoOpImporter(),
    )
    residual_repo = _ResidualRepo()
    service, _settlement, _warehouse, _preview, residuals = _finalize_case(
        plan,
        residual_repo=residual_repo,
    )
    result = service.execute(technician_id=_TECHNICIAN_ID)
    assert isinstance(result.committed_event, TechnicianReconciliationSessionCommitted)
    assert result.cleared_by_sku == result.committed_event.cleared_by_sku
    assert result.residual_by_sku == {"coffee": Decimal("-50")}
    assert len(residuals.saved) == 1
