from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationBlocked,
    ReconciliationSessionPlanner,
)
from src.application.technician_warehouse import (
    FinalizedTransferChangedError,
    ImportedTransferRef,
    MoySkladUnavailable,
    TechnicianWarehouseDelta,
    TechnicianWarehouseImportBlocked,
    TechnicianWarehouseImportResult,
    UnmatchedMsProduct,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-a")
_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)
_PREVIOUS_FINALIZED_AT = datetime(2026, 5, 10, tzinfo=UTC)


@dataclass
class _WarehouseDeltaPort:
    delta: TechnicianWarehouseDelta | None = None
    unmatched: tuple[UnmatchedMsProduct, ...] = ()
    error: Exception | None = None
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
class _RecordingImporter:
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)
    result: TechnicianWarehouseImportResult | None = None
    error: Exception | None = None

    async def execute(self, technician_id: TechnicianId, *, anchor_at: datetime):
        self.calls.append((technician_id, anchor_at))
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
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


def _session_warehouse_repo(
    *,
    inventory_id: str = "warehouse-inv-2",
    counted_at: datetime = _ANCHOR,
    closed: bool = False,
    has_session_inventory: bool = True,
) -> _WarehouseRepo:
    warehouse = MagicMock()
    warehouse.is_closed.return_value = closed
    if closed or not has_session_inventory:
        warehouse.compute_warehouse_delta_between_latest_inventories.return_value = None
    else:
        warehouse.compute_warehouse_delta_between_latest_inventories.return_value = SimpleNamespace(
            current_inventory_id=inventory_id,
            current_inventory_moment=counted_at,
        )
    return _WarehouseRepo(warehouse=warehouse)


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


def _planner(
    port: _WarehouseDeltaPort,
    *,
    importer: _RecordingImporter | None = None,
    warehouse_repository: _WarehouseRepo | None = None,
    period_repo: InMemoryPeriodReconciliationRepository | None = None,
) -> ReconciliationSessionPlanner:
    if period_repo is None:
        period_repo = InMemoryPeriodReconciliationRepository()
        period_repo.save(_snap("p1", 10))
    return ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=_settlement_with_previous_session(),
        warehouse_delta_port=port,
        warehouse_repository=warehouse_repository or _session_warehouse_repo(),
        importer=importer if importer is not None else _RecordingImporter(),
    )


def test_planner_resolves_inventory_cutoff_before_import() -> None:
    """happy: import moment_to = counted_at session inventory; get_delta until=cutoff."""
    cutoff = datetime(2026, 5, 20, tzinfo=UTC)
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=cutoff,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    importer = _RecordingImporter()
    plan = _planner(
        port,
        importer=importer,
        warehouse_repository=_session_warehouse_repo(counted_at=cutoff),
    ).plan(_TECHNICIAN_ID)
    assert plan.anchor_at == cutoff
    assert importer.calls == [(_TECHNICIAN_ID, cutoff)]
    assert port.calls == [(_TECHNICIAN_ID, _PREVIOUS_FINALIZED_AT, cutoff, True)]


def test_planner_no_inventory_raises_before_import() -> None:
    """error: нет eligible form inventory → raise до import."""
    importer = _RecordingImporter()
    with pytest.raises(
        ReconciliationBlocked,
        match="no technician warehouse inventory in window",
    ):
        _planner(
            _WarehouseDeltaPort(),
            importer=importer,
            warehouse_repository=_session_warehouse_repo(has_session_inventory=False),
        ).plan(_TECHNICIAN_ID)
    assert importer.calls == []


def test_planner_allows_single_form_inventory_cutoff() -> None:
    """happy: одна form inventory (eligible current) → cutoff = counted_at; import вызывается."""
    cutoff = datetime(2026, 5, 20, tzinfo=UTC)
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-form-1",
            inventory_moment=cutoff,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    importer = _RecordingImporter()
    plan = _planner(
        port,
        importer=importer,
        warehouse_repository=_session_warehouse_repo(
            inventory_id="warehouse-inv-form-1",
            counted_at=cutoff,
        ),
    ).plan(_TECHNICIAN_ID)
    assert plan.anchor_at == cutoff
    assert plan.warehouse_inventory_id == "warehouse-inv-form-1"
    assert importer.calls == [(_TECHNICIAN_ID, cutoff)]
    assert port.calls == [(_TECHNICIAN_ID, _PREVIOUS_FINALIZED_AT, cutoff, True)]


def test_planner_plan_has_no_anchor_at_parameter() -> None:
    """happy: public plan() не принимает anchor_at."""
    import inspect

    params = inspect.signature(ReconciliationSessionPlanner.plan).parameters
    assert "anchor_at" not in params


def test_planner_uses_domain_warehouse_delta_and_keeps_residual_formula() -> None:
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            calculated_stock_by_sku={"coffee": Decimal("5000")},
            actual_stock_by_sku={"coffee": Decimal("6000")},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    plan = _planner(port).plan(_TECHNICIAN_ID)
    assert plan.warehouse_inventory_id == "warehouse-inv-2"
    assert plan.residual_by_sku == {}
    assert port.calls == [(_TECHNICIAN_ID, _PREVIOUS_FINALIZED_AT, _ANCHOR, True)]


def test_planner_unmatched_products_do_not_block_finalize() -> None:
    """happy: unmatched из import_result не блокер; can_finalize от blockers."""
    importer = _RecordingImporter(
        result=TechnicianWarehouseImportResult(
            imported=0,
            updated=0,
            voided=0,
            ignored=0,
            skipped_unresolved=0,
            truncated_non_domain=0,
            transfer_refs=(),
            unmatched_products=(UnmatchedMsProduct("unknown", "Unknown", "move-unknown"),),
        ),
    )
    plan = _planner(
        _WarehouseDeltaPort(
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
        importer=importer,
    ).plan(_TECHNICIAN_ID)
    assert [item.product_code for item in plan.unmatched_products] == ["unknown"]
    assert "unknown" not in plan.blockers
    assert plan.can_finalize is True


def test_planner_propagates_ms_unavailable_as_blocker() -> None:
    plan = _planner(
        _WarehouseDeltaPort(error=MoySkladUnavailable("timeout")),
    ).plan(_TECHNICIAN_ID)
    assert "timeout" in plan.blockers


def test_planner_importer_ms_unavailable_blocks_without_get_delta() -> None:
    """error: MoySkladUnavailable на importer → blocker; get_delta не вызывается."""
    importer = _RecordingImporter(error=MoySkladUnavailable("timeout"))
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    plan = _planner(port, importer=importer).plan(_TECHNICIAN_ID)
    assert "timeout" in plan.blockers
    assert plan.can_finalize is False
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]
    assert port.calls == []


def test_planner_propagates_import_blocked_as_blocker() -> None:
    message = "TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES is required for import"
    plan = _planner(
        _WarehouseDeltaPort(error=TechnicianWarehouseImportBlocked(message)),
    ).plan(_TECHNICIAN_ID)
    assert message in plan.blockers
    assert plan.can_finalize is False


def test_planner_importer_unposted_ms_moves_block_finalize() -> None:
    """happy LOK-11: ImportBlocked от unposted → blockers / can_finalize=false."""
    from src.application.technician_warehouse.import_ms_transfers import (
        format_unposted_ms_moves_blocker,
    )

    message = format_unposted_ms_moves_blocker(document_ids=("ms-doc-1", "ms-doc-2"))
    importer = _RecordingImporter(error=TechnicianWarehouseImportBlocked(message))
    plan = _planner(_WarehouseDeltaPort(), importer=importer).plan(_TECHNICIAN_ID)
    assert message in plan.blockers
    assert plan.can_finalize is False
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]


def test_planner_propagates_finalized_transfer_changed_as_blocker() -> None:
    class _PortRaisingFinalized(_WarehouseDeltaPort):
        async def get_delta(
            self,
            technician_id: TechnicianId,
            *,
            after: datetime | None,
            until: datetime,
            skip_import: bool = False,
        ) -> TechnicianWarehouseDelta | None:
            self.calls.append((technician_id, after, until, skip_import))
            raise FinalizedTransferChangedError("move-1")

    plan = _planner(_PortRaisingFinalized()).plan(_TECHNICIAN_ID)
    assert "finalized MS transfer changed" in plan.blockers
    assert plan.can_finalize is False


def test_regular_plan_blocks_when_warehouse_closed() -> None:
    warehouse = MagicMock()
    warehouse.is_closed.return_value = True
    repo = _WarehouseRepo(warehouse=warehouse)
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
    planner = ReconciliationSessionPlanner(
        reconciliation_repo=period_repo,
        settlement_repository=InMemoryTechnicianSettlementRepository(
            event_store=InMemoryTechnicianSettlementEventStore(),
        ),
        warehouse_delta_port=_WarehouseDeltaPort(),
        warehouse_repository=repo,
        importer=_RecordingImporter(),
    )
    with pytest.raises(ReconciliationBlocked, match="exit-reconcile"):
        planner.plan(_TECHNICIAN_ID)


def test_planner_imports_before_pending_scope_block() -> None:
    """Образец pending: test_preview_blocks_on_pending_in_window (status=pending_sales)."""
    importer = _RecordingImporter()
    port = _WarehouseDeltaPort()
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p1", 10))
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
    planner = _planner(port, importer=importer, period_repo=period_repo)
    with pytest.raises(ReconciliationBlocked, match="pending periods"):
        planner.plan(_TECHNICIAN_ID)
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]
    assert port.calls == []


def test_planner_closed_warehouse_skips_import() -> None:
    importer = _RecordingImporter()
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="w",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    with pytest.raises(ReconciliationBlocked, match="warehouse is closed"):
        _planner(
            port,
            importer=importer,
            warehouse_repository=_session_warehouse_repo(closed=True),
        ).plan(_TECHNICIAN_ID)
    assert importer.calls == []
    assert port.calls == []


def test_planner_get_delta_uses_skip_import_true() -> None:
    importer = _RecordingImporter()
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={"coffee": Decimal("1000")},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    _planner(port, importer=importer).plan(_TECHNICIAN_ID)
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]
    assert port.calls == [(_TECHNICIAN_ID, _PREVIOUS_FINALIZED_AT, _ANCHOR, True)]


def test_planner_uses_import_transfer_refs_when_skip_import() -> None:
    importer = _RecordingImporter()
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=_ANCHOR,
            warehouse_delta_by_sku={},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),  # skip_import path empties refs on port
            unmatched_products=(),
        ),
    )
    plan = _planner(port, importer=importer).plan(_TECHNICIAN_ID)
    assert len(plan.transfer_refs) == 1
    assert plan.transfer_refs[0].external_document_id == "doc-1"


def test_planner_defers_periods_after_inventory_cutoff() -> None:
    """happy: closed_at > counted_at → deferred; в scope только ≤ cutoff."""
    cutoff = datetime(2026, 5, 15, tzinfo=UTC)
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p-in", 10))  # closed_at day=10 ≤ 15
    period_repo.save(_snap("p-out", 20))  # closed_at day=20 > 15
    port = _WarehouseDeltaPort(
        delta=TechnicianWarehouseDelta(
            warehouse_inventory_id="warehouse-inv-2",
            inventory_moment=cutoff,
            warehouse_delta_by_sku={"coffee": Decimal("2000")},
            calculated_stock_by_sku={},
            actual_stock_by_sku={},
            transfer_refs=(),
            unmatched_products=(),
        ),
    )
    plan = _planner(
        port,
        warehouse_repository=_session_warehouse_repo(counted_at=cutoff),
        period_repo=period_repo,
    ).plan(_TECHNICIAN_ID)
    assert [p.period_id for p in plan.scope.scope] == ["p-in"]
    assert [p.period_id for p in plan.scope.deferred] == ["p-out"]


def test_planner_empty_scope_raises_nothing_to_reconcile() -> None:
    """edge: все периоды после cutoff → nothing to reconcile in window."""
    cutoff = datetime(2026, 5, 5, tzinfo=UTC)
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(_snap("p-late", 20))
    with pytest.raises(ReconciliationBlocked, match="nothing to reconcile in window"):
        _planner(
            _WarehouseDeltaPort(
                delta=TechnicianWarehouseDelta(
                    warehouse_inventory_id="warehouse-inv-2",
                    inventory_moment=cutoff,
                    warehouse_delta_by_sku={},
                    calculated_stock_by_sku={},
                    actual_stock_by_sku={},
                    transfer_refs=(),
                    unmatched_products=(),
                ),
            ),
            warehouse_repository=_session_warehouse_repo(counted_at=cutoff),
            period_repo=period_repo,
        ).plan(_TECHNICIAN_ID)
