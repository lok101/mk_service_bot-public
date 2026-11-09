from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import MachineId

FULL_SLICE_KEY = "full"


@beartype
def make_pnl_id(period_id: str, *, slice_key: str = FULL_SLICE_KEY) -> str:
    return f"pnl:{period_id}:{slice_key}"


@beartype
@dataclass(frozen=True, slots=True)
class PnlWarning:
    code: str
    message: str
    sku: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class PeriodPnl:
    pnl_id: str
    period_id: str
    slice_key: str
    machine_id: MachineId
    opened_at: datetime
    closed_at: datetime
    revenue: Decimal
    cogs_expected: Decimal
    cogs_actual: Decimal
    allocated_shortage: Decimal
    allocated_surplus: Decimal
    opex: Decimal
    opex_breakdown: tuple[tuple[str, Decimal | None], ...]
    net_before_residual: Decimal
    net_after_shortage: Decimal
    warnings: tuple[PnlWarning, ...]
    location_id: str | None = None
    technician_id: str | None = None
