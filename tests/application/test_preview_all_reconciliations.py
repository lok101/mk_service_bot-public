from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.application.technician_settlement.preview_all_reconciliations import (
    PreviewAllTechniciansReconciliation,
)
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportResult,
    UnmatchedMsProduct,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.models import VendingMachine
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_ANCHOR = datetime(2026, 6, 15, 14, 30, tzinfo=UTC)
_OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_TECH_A = TechnicianId("10003")
_TECH_B = TechnicianId("10010")


@dataclass
class _NoOpImporter:
    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        _ = technician_id, anchor_at
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


class _WarehouseDeltaPort:
    def __init__(
        self,
        *,
        fail_for: frozenset[TechnicianId] | None = None,
        unmatched_for: frozenset[TechnicianId] | None = None,
    ) -> None:
        self._fail_for = fail_for or frozenset()
        self._unmatched_for = unmatched_for or frozenset()

    async def get_delta(self, technician_id, *, after, until, skip_import: bool = False):
        _ = after, until, skip_import
        if technician_id in self._fail_for:
            return None
        unmatched = ()
        if technician_id in self._unmatched_for:
            unmatched = (UnmatchedMsProduct("unknown", "Unknown", "move-unknown"),)
        return TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-1",
            inventory_moment=datetime(2026, 6, 10, tzinfo=UTC),
            warehouse_delta_by_sku={"coffee": Decimal("10")},
            calculated_stock_by_sku={"coffee": Decimal("20")},
            actual_stock_by_sku={"coffee": Decimal("30")},
            transfer_refs=(),
            unmatched_products=unmatched,
        )


class _Machines:
    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return VendingMachine(id=machine_id, name="Machine One")

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return "Ivan"

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return f"Tech {technician_id.value}"

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None


def _posted_snapshot(
    *,
    technician_id: TechnicianId = _TECH_A,
    period_id: str = "rev-1:rev-2",
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=technician_id,
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(
            ReconciliationLine(
                product_code="coffee",
                actual_prev=Decimal("0"),
                actual=Decimal("0"),
                calculated=Decimal("0"),
                delta=Decimal("1"),
                loads_total=Decimal("0"),
                sales_total=Decimal("0"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        reconciled=False,
    )


@dataclass
class _OpenWarehouseRepo:
    counted_at: datetime = _ANCHOR
    has_session_inventory: bool = True

    def get(self, technician_id: TechnicianId):
        _ = technician_id
        warehouse = MagicMock()
        warehouse.is_closed.return_value = False
        if self.has_session_inventory:
            warehouse.compute_warehouse_delta_between_latest_inventories.return_value = (
                SimpleNamespace(
                    current_inventory_id="warehouse-inv-1",
                    current_inventory_moment=self.counted_at,
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


def _build_use_case(
    repo: InMemoryPeriodReconciliationRepository,
    *,
    inv_port: _WarehouseDeltaPort | None = None,
    warehouse_repository: _OpenWarehouseRepo | None = None,
) -> PreviewAllTechniciansReconciliation:
    settlement_repo = InMemoryTechnicianSettlementRepository(
        InMemoryTechnicianSettlementEventStore(),
    )
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=repo,
        settlement_repository=settlement_repo,
        warehouse_delta_port=inv_port or _WarehouseDeltaPort(),
        warehouse_repository=warehouse_repository or _OpenWarehouseRepo(),
        importer=_NoOpImporter(),
    )
    preview = PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=InMemoryReconciliationDraftStore(),
    )
    return PreviewAllTechniciansReconciliation(
        reconciliation_repo=repo,
        preview=preview,
        machines=_Machines(),
    )


def test_preview_all_execute_has_no_anchor_at_parameter() -> None:
    import inspect

    params = inspect.signature(PreviewAllTechniciansReconciliation.execute).parameters
    assert "anchor_at" not in params


def test_preview_all_empty_candidates_returns_empty_result() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    use_case = _build_use_case(repo)

    result = use_case.execute()

    assert result.outcomes == ()
    assert result.processed == 0


def test_preview_all_mixed_statuses() -> None:
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_posted_snapshot(technician_id=_TECH_A))
    repo.save(
        _posted_snapshot(
            technician_id=_TECH_B,
            period_id="rev-3:rev-4",
        ),
    )
    inv_port = _WarehouseDeltaPort(fail_for=frozenset({_TECH_B}))
    use_case = _build_use_case(repo, inv_port=inv_port)

    result = use_case.execute()

    assert result.succeeded == 1
    assert result.blocked == 1
    assert result.outcomes[0].status == "ok"
    assert result.outcomes[1].status == "blocked"


def test_preview_all_does_not_block_on_legacy_unmatched_only() -> None:
    """edge: unmatched_for больше не даёт blocked."""
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(_posted_snapshot(technician_id=_TECH_A))
    repo.save(
        _posted_snapshot(
            technician_id=_TECH_B,
            period_id="rev-3:rev-4",
        ),
    )
    inv_port = _WarehouseDeltaPort(unmatched_for=frozenset({_TECH_B}))
    use_case = _build_use_case(repo, inv_port=inv_port)

    result = use_case.execute()

    assert result.succeeded == 2
    assert result.blocked == 0
    assert all(outcome.status == "ok" for outcome in result.outcomes)


def test_preview_all_empty_scope_is_skipped_not_dropped() -> None:
    """edge: техник с только post-cutoff периодами остаётся в outcomes как skipped."""
    repo = InMemoryPeriodReconciliationRepository()
    repo.save(
        ResponsibilityPeriodReconciliation(
            period_id="deferred-only:rev-2",
            machine_id=MachineId("vm-01"),
            responsible_technician_id=_TECH_A,
            opening_revision_id=RevisionId("rev-1"),
            closing_revision_id=RevisionId("rev-2"),
            opened_at=_OPENED,
            closed_at=datetime(2026, 6, 20, tzinfo=UTC),
            lines=(),
            sales_lines=(),
            load_count=0,
            status="complete",
            ledger_posted=True,
            reconciled=False,
        ),
    )
    use_case = _build_use_case(
        repo,
        warehouse_repository=_OpenWarehouseRepo(counted_at=_ANCHOR),
    )

    result = use_case.execute()

    assert result.skipped == 1
    assert result.outcomes[0].status == "skipped"
    assert result.outcomes[0].reason == "nothing to reconcile in window"
