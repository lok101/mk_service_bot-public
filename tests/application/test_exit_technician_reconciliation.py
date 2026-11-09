from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.exit_reconciliation import (
    FinalizeExitTechnicianReconciliation,
    PreviewExitTechnicianReconciliation,
)
from src.application.technician_settlement.list_technician_reconciliation_blockers import (
    ListTechnicianReconciliationBlockersResult,
    ReconciliationBlockerRow,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.aggregate import SessionCompletionResult
from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument
from src.domain.technician_warehouse.models import TechnicianWarehouseDelta
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECH = TechnicianId("tech-1")
_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


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


@dataclass
class _Blockers:
    pending_sales: tuple[ReconciliationBlockerRow, ...] = ()
    operational_open: tuple[ReconciliationBlockerRow, ...] = ()

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
            pending_sales=self.pending_sales,
            operational_open=self.operational_open,
        )


def _blocker_row(status: str) -> ReconciliationBlockerRow:
    return ReconciliationBlockerRow(
        machine_name="m1",
        opened_at="2026-05-01",
        assigned_technician="Ivan",
        status=status,
    )


def _closed_warehouse(*, delta_by_sku: dict[str, Decimal] | None = None):
    delta = TechnicianWarehouseDelta(
        current_inventory_id="exit-evt-1",
        current_inventory_moment=_NOW,
        previous_inventory_id="inv-b",
        previous_inventory_moment=datetime(2026, 7, 1, tzinfo=UTC),
        actual_by_sku={},
        calculated_by_sku={"coffee": Decimal("1")},
        delta_by_sku=delta_by_sku or {"coffee": Decimal("-1")},
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
    return warehouse


def _posted_ready_snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id="p1",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECH,
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


def _preview_uc(
    *,
    warehouse,
    reconciliation_repo: InMemoryPeriodReconciliationRepository | None = None,
    blockers: _Blockers | None = None,
    draft_store: InMemoryReconciliationDraftStore | None = None,
) -> PreviewExitTechnicianReconciliation:
    return PreviewExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=reconciliation_repo or InMemoryPeriodReconciliationRepository(),
        blockers=blockers or _Blockers(),
        draft_store=draft_store or InMemoryReconciliationDraftStore(),
    )


def test_exit_preview_blocks_when_warehouse_not_closed() -> None:
    warehouse = MagicMock()
    warehouse.is_closed.return_value = False
    uc = _preview_uc(warehouse=warehouse)
    with pytest.raises(ReconciliationBlocked, match="close-technician-warehouse"):
        uc.build_preview(technician_id=_TECH)


def test_exit_plan_reads_delta_without_calling_import() -> None:
    warehouse = _closed_warehouse()
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_posted_ready_snapshot())
    uc = PreviewExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=repo,
        blockers=_Blockers(),
        draft_store=InMemoryReconciliationDraftStore(),
    )
    preview = uc.build_preview(technician_id=_TECH)
    warehouse.latest_warehouse_delta.assert_called_once()
    assert not hasattr(uc, "warehouse_delta_port")
    assert preview.warehouse_inventory_id == "exit-evt-1"
    assert preview.actual_stock_by_sku == {}
    assert preview.deferred == ()
    assert preview.can_finalize is True


def test_exit_plan_blocks_on_empty_scope() -> None:
    uc = _preview_uc(warehouse=_closed_warehouse())
    with pytest.raises(ReconciliationBlocked, match="nothing to reconcile"):
        uc.build_preview(technician_id=_TECH)


def test_exit_plan_blocks_on_operational_open() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_posted_ready_snapshot())
    uc = _preview_uc(
        warehouse=_closed_warehouse(),
        reconciliation_repo=repo,
        blockers=_Blockers(operational_open=(_blocker_row("operational_open"),)),
    )
    with pytest.raises(ReconciliationBlocked, match="operational_open|blocker"):
        uc.build_preview(technician_id=_TECH)


def test_exit_plan_blocks_on_complete_unposted() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    posted = _posted_ready_snapshot()
    repo.save(posted)
    unposted = ResponsibilityPeriodReconciliation(
        period_id="p-unposted",
        machine_id=MachineId("vm-02"),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("r3"),
        closing_revision_id=RevisionId("r4"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 12, tzinfo=UTC),
        lines=posted.lines,
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=False,
    )
    repo.save(unposted)
    uc = _preview_uc(warehouse=_closed_warehouse(), reconciliation_repo=repo)
    with pytest.raises(ReconciliationBlocked, match="ledger_posted|unposted|complete"):
        uc.build_preview(technician_id=_TECH)


def test_exit_plan_blocks_on_pending_sales() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_posted_ready_snapshot())
    uc = _preview_uc(
        warehouse=_closed_warehouse(),
        reconciliation_repo=repo,
        blockers=_Blockers(pending_sales=(_blocker_row("pending_sales"),)),
    )
    with pytest.raises(ReconciliationBlocked, match="pending_sales|blocker"):
        uc.build_preview(technician_id=_TECH)


@dataclass
class _RecordingWarehouseFinalize:
    finalized_session_ids: list[str] = field(default_factory=list)

    def finalize_transfers(self, session_id: str) -> None:
        self.finalized_session_ids.append(session_id)


@dataclass
class _FailingOnceWarehouseFinalize(_RecordingWarehouseFinalize):
    should_fail: bool = True

    def finalize_transfers(self, session_id: str) -> None:
        if self.should_fail:
            self.should_fail = False
            raise RuntimeError("warehouse finalize failed")
        super().finalize_transfers(session_id)


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


def _exit_finalize_happy() -> tuple[
    SessionCompletionResult,
    _RecordingWarehouseFinalize,
    InMemoryPeriodReconciliationRepository,
    InMemoryReconciliationDraftStore,
]:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_posted_ready_snapshot())
    settlement = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    warehouse_finalize = _RecordingWarehouseFinalize()
    draft_store = InMemoryReconciliationDraftStore()
    warehouse = _closed_warehouse()
    PreviewExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=period_repo,
        blockers=_Blockers(),
        draft_store=draft_store,
    ).build_preview(technician_id=_TECH)
    result = FinalizeExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=period_repo,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement),
        settlement_repository=settlement,
        residual_repo=_ResidualRepo(),
        warehouse_finalize=warehouse_finalize,
        draft_store=draft_store,
    ).execute(technician_id=_TECH)
    return result, warehouse_finalize, period_repo, draft_store


def test_exit_finalize_session_id_unchanged() -> None:
    """happy regress: exit session_id остаётся {tech}:exit:{warehouse_inventory_id}."""
    result, warehouse_finalize, _period_repo, _draft_store = _exit_finalize_happy()
    assert result.session_id.value == f"{_TECH.value}:exit:exit-evt-1"
    assert ":exit:" in result.session_id.value
    assert warehouse_finalize.finalized_session_ids == [result.session_id.value]


def test_exit_finalize_sets_mode_exit_warehouse_closed() -> None:
    result, warehouse_finalize, period_repo, draft_store = _exit_finalize_happy()
    assert result.mode == "exit_warehouse_closed"
    assert result.deferred_period_ids == ()
    assert result.warehouse_inventory_id == "exit-evt-1"
    assert result.session_id.value == f"{_TECH.value}:exit:exit-evt-1"
    assert warehouse_finalize.finalized_session_ids == [result.session_id.value]
    assert period_repo.reconciled_periods == [("p1",)]
    assert draft_store.get(_TECH.value, "exit") is None


def _session_completed_count(settlement: InMemoryTechnicianSettlementRepository) -> int:
    from src.domain.technician_settlement import (
        TechnicianReconciliationSessionCommitted,
        TechnicianReconciliationSessionCompleted,
    )

    return sum(
        1
        for event in settlement.events
        if isinstance(
            event,
            (TechnicianReconciliationSessionCommitted, TechnicianReconciliationSessionCompleted),
        )
    )


def test_exit_finalize_retry_after_warehouse_finalize_failure_is_idempotent() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_posted_ready_snapshot())
    settlement = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    warehouse_finalize = _FailingOnceWarehouseFinalize()
    draft_store = InMemoryReconciliationDraftStore()
    warehouse = _closed_warehouse()
    PreviewExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=period_repo,
        blockers=_Blockers(),
        draft_store=draft_store,
    ).build_preview(technician_id=_TECH)
    uc = FinalizeExitTechnicianReconciliation(
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        reconciliation_repo=period_repo,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement),
        settlement_repository=settlement,
        residual_repo=_ResidualRepo(),
        warehouse_finalize=warehouse_finalize,
        draft_store=draft_store,
    )
    with pytest.raises(RuntimeError, match="warehouse finalize failed"):
        uc.execute(technician_id=_TECH)
    assert _session_completed_count(settlement) == 1

    result = uc.execute(technician_id=_TECH)
    assert _session_completed_count(settlement) == 1
    assert result.session_id.value == f"{_TECH.value}:exit:exit-evt-1"
    assert warehouse_finalize.finalized_session_ids == [result.session_id.value]
    assert draft_store.get(_TECH.value, "exit") is None


def test_exit_finalize_requires_warehouse_finalize_port() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_posted_ready_snapshot())
    settlement = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    with pytest.raises(TypeError, match="warehouse_finalize"):
        FinalizeExitTechnicianReconciliation(  # type: ignore[call-arg]
            warehouse_repository=_WarehouseRepo(warehouse=_closed_warehouse()),
            reconciliation_repo=period_repo,
            settlement_executor=TechnicianSettlementExecutor(repository=settlement),
            settlement_repository=settlement,
            residual_repo=_ResidualRepo(),
            draft_store=InMemoryReconciliationDraftStore(),
        )
