from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.ports import TechnicianSettlementEventStore
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)


@beartype
@dataclass(frozen=True, slots=True)
class WipeReport:
    settlement_events: int
    period_snapshots: int
    residual_documents: int
    reconciliation_drafts: int


@beartype
@dataclass(frozen=True, slots=True)
class WipeSettlementData:
    settlement_event_store: TechnicianSettlementEventStore
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    residual_repo: ReconciliationResidualDocumentRepository
    draft_store: ReconciliationDraftStore

    @beartype
    def preview(self) -> WipeReport:
        return WipeReport(
            settlement_events=self.settlement_event_store.count_all(),
            period_snapshots=self.reconciliation_repo.count_all(),
            residual_documents=self.residual_repo.count_all(),
            reconciliation_drafts=self.draft_store.count_all(),
        )

    @beartype
    def execute(self) -> WipeReport:
        report = self.preview()
        self.settlement_event_store.delete_all()
        self.reconciliation_repo.delete_all()
        self.residual_repo.delete_all()
        self.draft_store.delete_all()
        return report
