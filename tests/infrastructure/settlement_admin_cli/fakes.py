from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.finalize_reconciliation import (
    FinalizeTechnicianReconciliation,
)
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
    ReconciliationPreview,
)
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    CloseWarehouseDryRunReport,
    ImportedTransferRef,
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportResult,
)
from src.domain.ids import EventId, MachineId, ReconciliationSessionId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.aggregate import SessionCompletionResult
from src.domain.technician_settlement.events import (
    TechnicianReconciliationSessionCommitted,
)
from src.domain.technician_warehouse import TechnicianWarehouseExitClosed
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)
_TECHNICIAN_ID = TechnicianId("tech-1")


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
class _RecordingWarehouseDeltaPort:
    calls: int = 0

    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after,
        until,
        skip_import: bool = False,
    ):
        _ = technician_id, after, until, skip_import
        self.calls += 1
        return TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            calculated_stock_by_sku={"coffee": Decimal("5000")},
            actual_stock_by_sku={"coffee": Decimal("6000")},
            transfer_refs=(ImportedTransferRef("move-1", "hash-1"),),
            unmatched_products=(),
        )


class _NoOpWarehouseFinalize:
    def finalize_transfers(self, session_id: str) -> None:
        _ = session_id


@dataclass
class _RecordingPreview:
    preview: ReconciliationPreview
    audit_timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))

    def execute(self, *, technician_id: TechnicianId):
        _ = technician_id
        return self.preview


class _ResidualRepo:
    def save(self, document: object) -> None:
        _ = document

    def count_all(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0


@dataclass
class _OpenWarehouseRepo:
    def get(self, technician_id: TechnicianId):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        warehouse = MagicMock()
        warehouse.is_closed.return_value = False
        warehouse.latest_inventory_id = "warehouse-inv-2"
        warehouse.compute_warehouse_delta_between_latest_inventories.return_value = SimpleNamespace(
            current_inventory_id="warehouse-inv-2",
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


def _build_finalize(
    *,
    delta_port: _RecordingWarehouseDeltaPort,
) -> FinalizeTechnicianReconciliation:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    settlement_repository = InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )
    warehouse_repository = _OpenWarehouseRepo()
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=settlement_repository,
        warehouse_delta_port=delta_port,
        warehouse_repository=warehouse_repository,
        importer=_NoOpImporter(transfer_refs=(ImportedTransferRef("move-1", "hash-1"),)),
    )
    draft_store = InMemoryReconciliationDraftStore()
    PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=draft_store,
    ).execute(technician_id=_TECHNICIAN_ID)
    return FinalizeTechnicianReconciliation(
        draft_store=draft_store,
        warehouse_repository=warehouse_repository,
        settlement_executor=TechnicianSettlementExecutor(repository=settlement_repository),
        settlement_repository=settlement_repository,
        reconciliation_repo=period_repo,
        residual_repo=_ResidualRepo(),
        warehouse_finalize=_NoOpWarehouseFinalize(),
    )


@dataclass
class _RecordingCloseWarehouse:
    calls: list[tuple[TechnicianId, bool]] = field(default_factory=list)
    dry_run: CloseWarehouseDryRunReport | None = None
    closed: TechnicianWarehouseExitClosed | None = None
    error: Exception | None = None

    async def execute(
        self,
        *,
        technician_id: TechnicianId,
        closed_at: datetime | None = None,
        confirm: bool,
    ):
        _ = closed_at
        self.calls.append((technician_id, confirm))
        if self.error is not None:
            raise self.error
        if confirm:
            assert self.closed is not None
            return self.closed
        assert self.dry_run is not None
        return self.dry_run


@dataclass
class _RecordingFinalize:
    result: SessionCompletionResult
    calls: list[TechnicianId] = field(default_factory=list)
    fail_for: frozenset[str] = frozenset()

    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult:
        from src.application.technician_settlement import ReconciliationBlocked

        self.calls.append(technician_id)
        if technician_id.value in self.fail_for:
            raise ReconciliationBlocked("no reconciliation draft")
        return self.result


@dataclass
class _RecordingPreviewExit:
    preview: ReconciliationPreview
    calls: list[TechnicianId] = field(default_factory=list)

    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> ReconciliationPreview:
        self.calls.append(technician_id)
        return self.preview


@dataclass
class _RecordingFinalizeExit:
    result: SessionCompletionResult
    calls: list[TechnicianId] = field(default_factory=list)

    def execute(
        self,
        *,
        technician_id: TechnicianId,
    ) -> SessionCompletionResult:
        self.calls.append(technician_id)
        return self.result


@dataclass
class _SettlementAdminDeps:
    preview: _RecordingPreview | None = None
    preview_all: object | None = None
    finalize: FinalizeTechnicianReconciliation | None = None
    close_warehouse: _RecordingCloseWarehouse | None = None
    preview_exit: _RecordingPreviewExit | None = None
    finalize_exit: _RecordingFinalizeExit | None = None
    draft_store: InMemoryReconciliationDraftStore | None = None
    list_status: object | None = None
    list_blockers: object | None = None
    closed_warehouse_technician_ids: tuple[str, ...] = ()
    audit_timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Moscow"))


def _deps(**overrides: object) -> _SettlementAdminDeps:
    case = _SettlementAdminDeps()
    for key, value in overrides.items():
        setattr(case, key, value)
    return case


def _preview_args() -> list[str]:
    return ["reconcile", "preview", "--technician-id", "tech-1"]


def _finalize_args(*, confirm: bool) -> list[str]:
    args = [
        "reconcile",
        "finalize",
        "--technician-id",
        "tech-1",
    ]
    if confirm:
        args.append("--confirm")
    return args


def _regular_preview() -> ReconciliationPreview:
    return ReconciliationPreview(
        technician_id=_TECHNICIAN_ID,
        anchor_at=_ANCHOR,
        scope=(),
        deferred=(),
        ledger_balance_session={"coffee": Decimal("1")},
        warehouse_inventory_id="warehouse-inv-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("2")},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={"coffee": Decimal("3")},
        actual_stock_by_sku={"coffee": Decimal("5")},
        previous_actual_by_sku={"coffee": Decimal("1")},
        supply_in_by_sku={"coffee": Decimal("1")},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(),
        unmatched_products=(),
        blockers=(),
        can_finalize=True,
        residual_by_sku={"coffee": Decimal("3")},
    )


def _close_dry_run() -> CloseWarehouseDryRunReport:
    return CloseWarehouseDryRunReport(
        technician_id=_TECHNICIAN_ID,
        closed_at=_ANCHOR,
        return_external_document_id="ret-1",
        return_content_hash="hash-ret-1",
        planned_delta_by_sku={"coffee": Decimal("-10")},
        previous_inventory_id="synthetic_zero_baseline",
    )


def _exit_closed_event() -> TechnicianWarehouseExitClosed:
    return TechnicianWarehouseExitClosed(
        event_id=EventId("exit-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_ANCHOR,
        closed_at=_ANCHOR,
        return_external_document_id="ret-1",
        return_content_hash="hash-ret-1",
    )


def _exit_finalize_result() -> SessionCompletionResult:
    session_id = ReconciliationSessionId("tech-1:exit:inv-1")
    committed = TechnicianReconciliationSessionCommitted(
        event_id=EventId("sess-1"),
        session_id=session_id,
        technician_id=_TECHNICIAN_ID,
        mode="exit_warehouse_closed",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="inv-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={},
        cleared_by_sku={},
        residual_by_sku={},
        finalized_at=_ANCHOR,
        executed_at=_ANCHOR,
        occurred_at=_ANCHOR,
    )
    return SessionCompletionResult.from_committed(committed)


def _inventory_finalize_result() -> SessionCompletionResult:
    session_id = ReconciliationSessionId("tech-1:2026-05-25T00:00:00+00:00")
    committed = TechnicianReconciliationSessionCommitted(
        event_id=EventId("sess-inv-1"),
        session_id=session_id,
        technician_id=_TECHNICIAN_ID,
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={},
        cleared_by_sku={},
        residual_by_sku={},
        finalized_at=_ANCHOR,
        executed_at=_ANCHOR,
        occurred_at=_ANCHOR,
    )
    return SessionCompletionResult.from_committed(committed)


def _draft(
    *,
    technician_id: str = "tech-1",
    kind: str = "inventory",
) -> object:
    from src.application.technician_settlement.draft import ReconciliationDraft

    return ReconciliationDraft(
        technician_id=technician_id,
        kind=kind,  # type: ignore[arg-type]
        warehouse_inventory_id="inv-1",
        warehouse_inventory_moment=_ANCHOR,
        plan={"mode": kind, "period_ids": ["p1"]},
        updated_at=_ANCHOR,
        anchor_at=_ANCHOR if kind == "inventory" else None,
    )
