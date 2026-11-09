from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.domain.ids import ReconciliationSessionId, ResidualDocumentId, TechnicianId
from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument
from src.infrastructure.mongodb.reconciliation_residual_documents import (
    MongoReconciliationResidualDocumentRepository,
)


def _repo() -> MongoReconciliationResidualDocumentRepository:
    collection = mongomock.MongoClient().db.reconciliation_residual_documents
    return MongoReconciliationResidualDocumentRepository(_collection=collection)


def test_save_and_count_and_delete() -> None:
    repo = _repo()
    repo.save(
        ReconciliationResidualDocument(
            residual_document_id=ResidualDocumentId("res-1"),
            session_id=ReconciliationSessionId("sess-1"),
            technician_id=TechnicianId("tech-a"),
            kind="shortage",
            residual_by_sku={"coffee": Decimal("-50")},
            created_at=datetime(2026, 5, 25, tzinfo=UTC),
        ),
    )
    assert repo.count_all() == 1
    repo.save(
        ReconciliationResidualDocument(
            residual_document_id=ResidualDocumentId("res-1"),
            session_id=ReconciliationSessionId("sess-1"),
            technician_id=TechnicianId("tech-a"),
            kind="shortage",
            residual_by_sku={"coffee": Decimal("-50")},
            created_at=datetime(2026, 5, 25, tzinfo=UTC),
        ),
    )
    assert repo.count_all() == 1
    assert repo.delete_all() == 1
    assert repo.count_all() == 0
