from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.application.inventory_reconciliation import VerifyPortionSalesHoldingError
from src.application.outbox.settlement_portion_reconcile import SettlementPortionReconcileHandler
from src.application.technician_settlement.preview_reconciliation import (
    PreviewTechnicianReconciliation,
    ReconciliationPreview,
)
from src.application.technician_settlement.reconciliation_planner import (
    EmptyReconcileScope,
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
from src.domain.technician_settlement.portion_events import SettlementPortionReconcileRequested
from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument
from src.domain.technician_warehouse import TechnicianWarehouse
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECH = TechnicianId("tech-a")
_INV_OLD = "inv-old"
_INV_NEW = "inv-new"
_T_OLD = datetime(2026, 5, 10, tzinfo=UTC)
_T_NEW = datetime(2026, 5, 25, tzinfo=UTC)
_MOMENT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _FakeFinalize:
    calls: list[TechnicianId] = field(default_factory=list)

    def execute(self, *, technician_id: TechnicianId) -> object:
        self.calls.append(technician_id)
        return SimpleNamespace(ok=True)


@dataclass
class _FakePreview:
    preview: ReconciliationPreview | None = None
    error: Exception | None = None
    calls: list[tuple[TechnicianId, str, bool]] = field(default_factory=list)

    def build_preview_for_inventory(
        self,
        *,
        technician_id: TechnicianId,
        warehouse_inventory_id: str,
        skip_import: bool = True,
    ) -> ReconciliationPreview:
        self.calls.append((technician_id, warehouse_inventory_id, skip_import))
        if self.error is not None:
            raise self.error
        assert self.preview is not None
        return self.preview


@dataclass
class _SpyImporter:
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)
    raises: Exception | None = None

    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult:
        self.calls.append((technician_id, anchor_at))
        if self.raises is not None:
            raise self.raises
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
class _SpyVerifier:
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)
    raises: Exception | None = None

    def execute(self, *, technician_id: TechnicianId, cutoff: datetime) -> object:
        self.calls.append((technician_id, cutoff))
        if self.raises is not None:
            raise self.raises
        return object()


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


def _handler(
    *,
    preview: object,
    finalize: _FakeFinalize | None = None,
    importer: object | None = None,
    verifier: object | None = None,
    residual_repo: _ResidualRepo | None = None,
) -> SettlementPortionReconcileHandler:
    return SettlementPortionReconcileHandler(
        preview=preview,  # type: ignore[arg-type]
        finalize=finalize or _FakeFinalize(),
        importer=importer or _SpyImporter(),  # type: ignore[arg-type]
        verifier=verifier or _SpyVerifier(),  # type: ignore[arg-type]
        residual_repo=residual_repo or _ResidualRepo(),
    )


@dataclass
class _WarehouseDeltaPort:
    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None:
        _ = technician_id, after, until, skip_import
        return None


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


def _snap(period_id: str, day: int) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECH,
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


def _warehouse_with_two_inventories() -> TechnicianWarehouse:
    warehouse = TechnicianWarehouse.empty(_TECH)
    warehouse.count_inventory(
        inventory_id=_INV_OLD,
        form_token="token-old",
        counted_at=_T_OLD,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    warehouse.count_inventory(
        inventory_id=_INV_NEW,
        form_token="token-new",
        counted_at=_T_NEW,
        actual_by_sku={"coffee": Decimal("8")},
        baseline=False,
    )
    warehouse.clear_pending_events()
    return warehouse


def _real_preview(
    *,
    warehouse: TechnicianWarehouse,
    period_day: int = 8,
) -> tuple[PreviewTechnicianReconciliation, InMemoryReconciliationDraftStore]:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", period_day))
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(),
        warehouse_repository=_WarehouseRepo(warehouse=warehouse),
        importer=_NoOpImporter(),
    )
    draft_store = InMemoryReconciliationDraftStore()
    preview = PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=draft_store,
    )
    return preview, draft_store


def _event(*, inventory_id: str = _INV_OLD) -> SettlementPortionReconcileRequested:
    return SettlementPortionReconcileRequested(
        event_id=EventId(f"portion:tech-a:{inventory_id}:reconcile"),
        technician_id=_TECH,
        warehouse_inventory_id=inventory_id,
        warehouse_inventory_moment=_T_OLD if inventory_id == _INV_OLD else _T_NEW,
        occurred_at=_MOMENT,
    )


def _preview_result(*, can_finalize: bool, inventory_id: str = _INV_OLD) -> ReconciliationPreview:
    return ReconciliationPreview(
        technician_id=_TECH,
        anchor_at=_T_OLD,
        scope=(),
        deferred=(),
        ledger_balance_session={},
        warehouse_inventory_id=inventory_id,
        warehouse_inventory_moment=_T_OLD,
        warehouse_delta_by_sku={},
        warehouse_source="domain_technician_warehouse",
        calculated_stock_by_sku={},
        actual_stock_by_sku={},
        previous_actual_by_sku={},
        supply_in_by_sku={},
        returns_by_sku={},
        loadings_by_sku={},
        transfer_refs=(ImportedTransferRef("doc-1", "hash-1"),),
        unmatched_products=(),
        blockers=() if can_finalize else ("pending_sales blocker",),
        can_finalize=can_finalize,
        residual_by_sku={},
    )


def test_reconcile_uses_payload_inventory_not_latest() -> None:
    # happy: payload inv-old while warehouse latest is inv-new
    warehouse = _warehouse_with_two_inventories()
    preview, draft_store = _real_preview(warehouse=warehouse)
    finalize = _FakeFinalize()
    handler = _handler(preview=preview, finalize=finalize)

    asyncio.run(handler.process(_event(inventory_id=_INV_OLD)))

    draft = draft_store.get(_TECH.value, "inventory")
    assert draft is not None
    assert draft.warehouse_inventory_id == _INV_OLD
    assert finalize.calls == [_TECH]


def test_reconcile_handler_finalize_signature_without_write_audit() -> None:
    """happy: finalize called as execute(technician_id=...) only."""
    finalize = _FakeFinalize()
    handler = _handler(
        preview=_FakePreview(preview=_preview_result(can_finalize=True)),
        finalize=finalize,
    )

    asyncio.run(handler.process(_event()))

    assert finalize.calls == [_TECH]


def test_reconcile_empty_scope_acks_without_finalize() -> None:
    # edge: empty scope + zero delta → ack success, no finalize, no residual
    preview = _FakePreview(
        error=EmptyReconcileScope(
            warehouse_delta_by_sku={},
            residual_by_sku={},
            warehouse_inventory_id=_INV_OLD,
            warehouse_inventory_moment=_T_OLD,
        ),
    )
    finalize = _FakeFinalize()
    residual_repo = _ResidualRepo()
    handler = _handler(preview=preview, finalize=finalize, residual_repo=residual_repo)

    asyncio.run(handler.process(_event()))

    assert finalize.calls == []
    assert residual_repo.saved == []
    assert preview.calls == [(_TECH, _INV_OLD, True)]


def test_reconcile_empty_scope_persists_residual_when_delta_nonzero() -> None:
    # happy: empty scope + non-zero warehouse_delta → residual persisted, no finalize
    residual = {"coffee": Decimal("-2")}
    preview = _FakePreview(
        error=EmptyReconcileScope(
            warehouse_delta_by_sku=residual,
            residual_by_sku=residual,
            warehouse_inventory_id=_INV_OLD,
            warehouse_inventory_moment=_T_OLD,
        ),
    )
    finalize = _FakeFinalize()
    residual_repo = _ResidualRepo()
    handler = _handler(preview=preview, finalize=finalize, residual_repo=residual_repo)

    asyncio.run(handler.process(_event()))

    assert finalize.calls == []
    assert len(residual_repo.saved) == 1
    doc = residual_repo.saved[0]
    assert doc.technician_id == _TECH
    assert doc.kind == "shortage"
    assert doc.residual_by_sku == residual
    assert doc.session_id.value == f"empty-scope:{_TECH.value}:{_INV_OLD}"


def test_reconcile_can_finalize_calls_finalize() -> None:
    # happy: can_finalize → finalize(technician_id=...)
    finalize = _FakeFinalize()
    handler = _handler(
        preview=_FakePreview(preview=_preview_result(can_finalize=True)),
        finalize=finalize,
    )

    asyncio.run(handler.process(_event()))

    assert finalize.calls == [_TECH]


def test_reconcile_blockers_fail_closed() -> None:
    # error: !can_finalize → raise (retry/DLQ)
    finalize = _FakeFinalize()
    residual_repo = _ResidualRepo()
    handler = _handler(
        preview=_FakePreview(preview=_preview_result(can_finalize=False)),
        finalize=finalize,
        residual_repo=residual_repo,
    )

    with pytest.raises(RuntimeError, match="portion reconcile blocked"):
        asyncio.run(handler.process(_event()))

    assert finalize.calls == []
    assert residual_repo.saved == []


def test_reconcile_handler_resyncs_transfers_and_sales_before_preview() -> None:
    # happy: importer + verifier are called with event technician_id/moment before preview
    warehouse = _warehouse_with_two_inventories()
    preview, draft_store = _real_preview(warehouse=warehouse)
    finalize = _FakeFinalize()
    importer = _SpyImporter()
    verifier = _SpyVerifier()
    handler = _handler(
        preview=preview,
        finalize=finalize,
        importer=importer,
        verifier=verifier,
    )

    asyncio.run(handler.process(_event(inventory_id=_INV_OLD)))

    assert importer.calls == [(_TECH, _T_OLD)]
    assert verifier.calls == [(_TECH, _T_OLD)]
    assert finalize.calls == [_TECH]
    draft = draft_store.get(_TECH.value, "inventory")
    assert draft is not None


def test_reconcile_handler_sync_resync_failure_fails_closed() -> None:
    # error: importer resync raises → fails closed, preview/finalize not called
    preview = _FakePreview(preview=_preview_result(can_finalize=True))
    finalize = _FakeFinalize()
    importer = _SpyImporter(raises=RuntimeError("moysklad unavailable"))
    verifier = _SpyVerifier()
    handler = _handler(
        preview=preview,
        finalize=finalize,
        importer=importer,
        verifier=verifier,
    )

    with pytest.raises(RuntimeError, match="moysklad unavailable"):
        asyncio.run(handler.process(_event()))

    assert verifier.calls == []
    assert preview.calls == []
    assert finalize.calls == []


def test_reconcile_handler_verify_resync_holding_fails_closed() -> None:
    # error: verifier resync raises holding → fails closed, finalize not called
    preview = _FakePreview(preview=_preview_result(can_finalize=True))
    finalize = _FakeFinalize()
    importer = _SpyImporter()
    verifier = _SpyVerifier(raises=VerifyPortionSalesHoldingError("holding on resync"))
    handler = _handler(
        preview=preview,
        finalize=finalize,
        importer=importer,
        verifier=verifier,
    )

    with pytest.raises(VerifyPortionSalesHoldingError):
        asyncio.run(handler.process(_event()))

    assert importer.calls == [(_TECH, _T_OLD)]
    assert preview.calls == []
    assert finalize.calls == []
