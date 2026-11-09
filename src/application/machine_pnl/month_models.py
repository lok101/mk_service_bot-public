from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.models import PnlWarning
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class MonthPnlSnapshot:
    machine_id: MachineId
    location_id: str | None
    technician_id: str | None
    period_start: date
    period_end: date
    revenue: Decimal
    revenue_known_as_of: date
    cogs_expected: Decimal
    cogs_actual_fact: Decimal
    cogs_actual_estimate: Decimal
    allocated_shortage_fact: Decimal
    allocated_shortage_estimate: Decimal
    allocated_surplus_fact: Decimal
    allocated_surplus_estimate: Decimal
    opex_breakdown: tuple[tuple[str, Decimal | None], ...]
    opex_known_total: Decimal
    net_theory: Decimal
    machine_gap: Decimal
    net_machine: Decimal
    tech_gap: Decimal
    net_after_tech: Decimal
    coverage_days: int
    days_in_month: int
    coverage_pct: Decimal
    projection_basis: str
    warnings: tuple[PnlWarning, ...]
    last_recomputed_at: datetime
    company_id: int | None = None
