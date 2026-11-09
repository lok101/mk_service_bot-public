from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.coverage import ReconciliationStatus
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.quantities import LoadInputUnit

CalculatedSource = Literal["domain"]


@beartype
@dataclass(frozen=True, slots=True)
class FrozenLoadLine:
    product_code: str
    occurred_at: datetime
    input_quantity: Decimal
    input_unit: LoadInputUnit
    pack_size: Decimal
    base_quantity: Decimal
    loading_event_id: str


@beartype
@dataclass(frozen=True, slots=True)
class FrozenSalesLine:
    product_code: str
    quantity: Decimal
    occurred_at: datetime
    source_id: str


@beartype
@dataclass(frozen=True, slots=True)
class ResponsibilityPeriodReconciliation:
    period_id: str
    machine_id: MachineId
    responsible_technician_id: TechnicianId
    opening_revision_id: RevisionId
    closing_revision_id: RevisionId
    opened_at: datetime
    closed_at: datetime
    lines: tuple[ReconciliationLine, ...]
    sales_lines: tuple[FrozenSalesLine, ...]
    load_count: int
    status: ReconciliationStatus
    load_lines: tuple[FrozenLoadLine, ...] = ()
    calculated_source: CalculatedSource = "domain"
    ledger_posted: bool = False
    reconciled: bool = False
    location_name: str = ""
    technician_name: str = ""
