from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import ReconciliationSessionId, ResidualDocumentId, TechnicianId
from src.domain.technician_settlement.residual_document import (
    ReconciliationResidualDocument,
    residual_kind_for,
)


def test_residual_document_shortage() -> None:
    doc = ReconciliationResidualDocument(
        residual_document_id=ResidualDocumentId("res-1"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        kind="shortage",
        residual_by_sku={"coffee": Decimal("-50")},
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    assert doc.kind == "shortage"
    assert doc.residual_by_sku["coffee"] == Decimal("-50")


def test_residual_kind_for_all_zeros_returns_none() -> None:
    assert residual_kind_for({"coffee": Decimal("0")}) is None


def test_residual_kind_for_negative_total_is_shortage() -> None:
    assert residual_kind_for({"coffee": Decimal("-50")}) == "shortage"


def test_residual_kind_for_positive_total_is_surplus() -> None:
    assert residual_kind_for({"a": Decimal("10"), "b": Decimal("5")}) == "surplus"
