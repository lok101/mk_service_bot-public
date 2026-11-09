from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import ReconciliationSessionId, ResidualDocumentId, TechnicianId

ResidualKind = Literal["shortage", "surplus"]


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationResidualDocument:
    residual_document_id: ResidualDocumentId
    session_id: ReconciliationSessionId
    technician_id: TechnicianId
    kind: ResidualKind
    residual_by_sku: dict[str, Decimal]
    created_at: datetime


@beartype
def residual_kind_for(residual_by_sku: dict[str, Decimal]) -> ResidualKind | None:
    total = sum(residual_by_sku.values(), Decimal("0"))
    if all(value == 0 for value in residual_by_sku.values()):
        return None
    if total < 0:
        return "shortage"
    return "surplus"
