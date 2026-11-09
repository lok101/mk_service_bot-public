from __future__ import annotations

from datetime import UTC, datetime

from src.application.technician_settlement.draft import ReconciliationDraft
from src.application.technician_settlement.wipe import WipeSettlementData
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)


class _ResidualRepo:
    def count_all(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0

    def save(self, document) -> None:
        pass


def test_wipe_deletes_reconciliation_drafts() -> None:
    drafts = InMemoryReconciliationDraftStore()
    drafts.upsert(
        ReconciliationDraft(
            technician_id="10001",
            kind="inventory",
            warehouse_inventory_id="inv-1",
            warehouse_inventory_moment=datetime(2026, 6, 10, tzinfo=UTC),
            plan={"mode": "inventory_delta", "period_ids": ["p1"]},
            updated_at=datetime(2026, 6, 15, tzinfo=UTC),
            anchor_at=datetime(2026, 6, 15, tzinfo=UTC),
        ),
    )
    wipe = WipeSettlementData(
        InMemoryTechnicianSettlementEventStore(),
        InMemoryPeriodReconciliationRepository(),
        _ResidualRepo(),
        drafts,
    )
    report = wipe.execute()
    assert report.reconciliation_drafts == 1
    assert drafts.count_all() == 0
