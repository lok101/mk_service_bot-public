from __future__ import annotations

from src.application.technician_settlement.wipe import WipeReport, WipeSettlementData
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)


class _CountingEventStore(InMemoryTechnicianSettlementEventStore):
    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count
        self.deleted = False

    def count_all(self) -> int:
        return self._count

    def delete_all(self) -> int:
        self.deleted = True
        return self._count


class _CountingPeriodRepo(InMemoryPeriodReconciliationRepository):
    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count
        self.deleted = False

    def count_all(self) -> int:
        return self._count

    def delete_all(self) -> int:
        self.deleted = True
        return self._count


class _ResidualRepo:
    def __init__(self, n: int) -> None:
        self._n = n
        self.deleted = False

    def save(self, document) -> None:
        pass

    def count_all(self) -> int:
        return self._n

    def delete_all(self) -> int:
        self.deleted = True
        return self._n


class _CountingDraftStore(InMemoryReconciliationDraftStore):
    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count
        self.deleted = False

    def count_all(self) -> int:
        return self._count

    def delete_all(self) -> None:
        self.deleted = True


def test_preview_counts_without_deleting() -> None:
    store = _CountingEventStore(3)
    periods = _CountingPeriodRepo(5)
    residual = _ResidualRepo(2)
    drafts = _CountingDraftStore(4)
    use_case = WipeSettlementData(store, periods, residual, drafts)
    report = use_case.preview()
    assert report == WipeReport(
        settlement_events=3,
        period_snapshots=5,
        residual_documents=2,
        reconciliation_drafts=4,
    )
    assert not store.deleted and not periods.deleted and not residual.deleted
    assert not drafts.deleted


def test_execute_deletes_all() -> None:
    store = _CountingEventStore(3)
    periods = _CountingPeriodRepo(5)
    residual = _ResidualRepo(2)
    drafts = _CountingDraftStore(4)
    use_case = WipeSettlementData(store, periods, residual, drafts)
    report = use_case.execute()
    assert report.settlement_events == 3
    assert report.reconciliation_drafts == 4
    assert store.deleted and periods.deleted and residual.deleted and drafts.deleted
