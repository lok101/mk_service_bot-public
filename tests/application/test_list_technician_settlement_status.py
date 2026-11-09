from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from src.application.technician_settlement.list_status import ListTechnicianSettlementStatus
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.testing.settlement_fakes import InMemoryPeriodReconciliationRepository
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
)


@dataclass
class _WarehouseRepo:
    closed_by_id: dict[str, bool]

    def get(self, technician_id: TechnicianId):
        warehouse = MagicMock()
        warehouse.is_closed.return_value = self.closed_by_id.get(technician_id.value, False)
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
class _Machines:
    names: dict[str, str]

    def get(self, machine_id: MachineId):  # pragma: no cover - protocol stub
        _ = machine_id
        return None

    def list_all(self):  # pragma: no cover
        return []

    def list_available_for_technician(self, technician_id: TechnicianId):  # pragma: no cover
        _ = technician_id
        return []

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        _ = machine_id
        return None

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        _ = machine_id
        return None

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return self.names.get(technician_id.value)


def _posted_unreconciled(
    technician_id: TechnicianId,
    period_id: str,
    *,
    opened_at: datetime,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=technician_id,
        opening_revision_id=RevisionId("r1"),
        closing_revision_id=RevisionId("r2"),
        opened_at=opened_at,
        closed_at=opened_at.replace(day=min(opened_at.day + 1, 28)),
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
        reconciled=False,
    )


def _baseline_event(
    technician_id: TechnicianId,
    event_id: str,
) -> TechnicianWarehouseInventoryCounted:
    occurred_at = datetime(2026, 5, 1, tzinfo=UTC)
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId(event_id),
        technician_id=technician_id,
        occurred_at=occurred_at,
        inventory_id=f"inv-{event_id}",
        form_token=f"tok-{event_id}",
        counted_at=occurred_at,
        lines=(("coffee", Decimal("1")),),
        baseline=True,
    )


def test_list_status_enriched_union_count_oldest_and_sort() -> None:
    event_store = InMemoryTechnicianWarehouseEventStore()
    event_store.append(TechnicianId("10004"), 0, (_baseline_event(TechnicianId("10004"), "o4"),))
    event_store.append(TechnicianId("10003"), 0, (_baseline_event(TechnicianId("10003"), "o3"),))
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10003"),
            "p-3a",
            opened_at=datetime(2026, 7, 10, 14, 15, tzinfo=UTC),
        )
    )
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10003"),
            "p-3b",
            opened_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        )
    )
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10001"),
            "p-1a",
            opened_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        )
    )
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10001"),
            "p-1b",
            opened_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        )
    )
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10001"),
            "p-1c",
            opened_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        )
    )
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("10002"),
            "p-2",
            opened_at=datetime(2026, 6, 15, 9, 30, tzinfo=UTC),
        )
    )

    report = ListTechnicianSettlementStatus(
        warehouse_event_store=event_store,
        warehouse_repository=_WarehouseRepo(
            closed_by_id={
                "10001": True,
                "10002": True,
                "10003": False,
                "10004": False,
            },
        ),
        period_repository=period_repo,
        machines=_Machines(
            names={
                "10001": "Иванов И.",
                "10002": "Петров П.",
                "10003": "Сидоров С.",
                "10004": "Козлов К.",
            },
        ),
    ).execute()

    assert [row.technician_id for row in report.rows] == [
        "10001",
        "10002",
        "10003",
        "10004",
    ]
    assert report.rows[0].technician_label == "Иванов И. (10001)"
    assert report.rows[0].warehouse_open is False
    assert report.rows[0].unreconciled_count == 3
    assert report.rows[0].oldest_opened_at == datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    assert report.rows[1].unreconciled_count == 1
    assert report.rows[2].warehouse_open is True
    assert report.rows[2].unreconciled_count == 2
    assert report.rows[2].oldest_opened_at == datetime(2026, 7, 10, 14, 15, tzinfo=UTC)
    assert report.rows[3].warehouse_open is True
    assert report.rows[3].unreconciled_count == 0
    assert report.rows[3].oldest_opened_at is None


def test_list_status_enriched_empty_union() -> None:
    report = ListTechnicianSettlementStatus(
        warehouse_event_store=InMemoryTechnicianWarehouseEventStore(),
        warehouse_repository=_WarehouseRepo(closed_by_id={}),
        period_repository=InMemoryPeriodReconciliationRepository(),
        machines=_Machines(names={}),
    ).execute()
    assert report.rows == ()


def test_list_status_enriched_missing_display_name() -> None:
    period_repo = InMemoryPeriodReconciliationRepository()
    period_repo.save(
        _posted_unreconciled(
            TechnicianId("99999"),
            "p-x",
            opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
    )
    report = ListTechnicianSettlementStatus(
        warehouse_event_store=InMemoryTechnicianWarehouseEventStore(),
        warehouse_repository=_WarehouseRepo(closed_by_id={"99999": True}),
        period_repository=period_repo,
        machines=_Machines(names={}),
    ).execute()
    assert len(report.rows) == 1
    assert report.rows[0].technician_label == "не найден в таблице (99999)"
    assert report.rows[0].warehouse_open is False
