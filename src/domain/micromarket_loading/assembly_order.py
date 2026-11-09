from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from beartype import beartype


class AssemblyOrderStatus(StrEnum):
    OPEN = "open"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketAssemblyOrderLine:
    catalog_code: str
    qty: Decimal

    def __post_init__(self) -> None:
        code = self.catalog_code.strip()
        if not code:
            raise ValueError("catalog_code must be non-empty")
        if self.qty <= 0:
            raise ValueError("qty must be positive")
        object.__setattr__(self, "catalog_code", code)


@beartype
@dataclass(frozen=True, slots=True)
class DuplicateCatalogCode:
    catalog_code: str


@beartype
@dataclass(frozen=True, slots=True)
class InvalidAssemblyOrderTransition:
    reason: str


@beartype
@dataclass(slots=True)
class MicromarketAssemblyOrder:
    order_id: str
    machine_code: str
    lines: tuple[MicromarketAssemblyOrderLine, ...]
    status: AssemblyOrderStatus = AssemblyOrderStatus.OPEN
    created_at: datetime | None = None
    alerted_days: set[date] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("order_id must be non-empty")
        if not self.machine_code.strip():
            raise ValueError("machine_code must be non-empty")
        if not self.lines:
            raise ValueError("lines must be non-empty")
        seen: set[str] = set()
        for line in self.lines:
            if line.catalog_code in seen:
                raise ValueError(f"duplicate catalog_code in order: {line.catalog_code}")
            seen.add(line.catalog_code)

    @beartype
    def with_lines(
        self,
        lines: tuple[MicromarketAssemblyOrderLine, ...],
    ) -> MicromarketAssemblyOrder | InvalidAssemblyOrderTransition:
        if self.status is not AssemblyOrderStatus.OPEN:
            return InvalidAssemblyOrderTransition("order is not open")
        if not lines:
            return InvalidAssemblyOrderTransition("lines must be non-empty")
        return MicromarketAssemblyOrder(
            order_id=self.order_id,
            machine_code=self.machine_code,
            lines=lines,
            status=self.status,
            created_at=self.created_at,
            alerted_days=set(self.alerted_days),
        )

    @beartype
    def cancel(self) -> MicromarketAssemblyOrder | InvalidAssemblyOrderTransition:
        if self.status is not AssemblyOrderStatus.OPEN:
            return InvalidAssemblyOrderTransition("order is not open")
        return MicromarketAssemblyOrder(
            order_id=self.order_id,
            machine_code=self.machine_code,
            lines=self.lines,
            status=AssemblyOrderStatus.CANCELLED,
            created_at=self.created_at,
            alerted_days=set(self.alerted_days),
        )

    @beartype
    def consume(self) -> MicromarketAssemblyOrder | InvalidAssemblyOrderTransition:
        if self.status is not AssemblyOrderStatus.OPEN:
            return InvalidAssemblyOrderTransition("order is not open")
        return MicromarketAssemblyOrder(
            order_id=self.order_id,
            machine_code=self.machine_code,
            lines=self.lines,
            status=AssemblyOrderStatus.CONSUMED,
            created_at=self.created_at,
            alerted_days=set(self.alerted_days),
        )

    @beartype
    def was_alerted(self, *, operational_day: date) -> bool:
        return operational_day in self.alerted_days

    @beartype
    def record_alert(self, *, operational_day: date) -> None:
        self.alerted_days.add(operational_day)


@beartype
def find_duplicate_on_machine(
    *,
    machine_code: str,
    candidate_codes: tuple[str, ...],
    open_orders: tuple[MicromarketAssemblyOrder, ...],
    exclude_order_id: str | None = None,
) -> DuplicateCatalogCode | None:
    occupied: set[str] = set()
    for order in open_orders:
        if order.status is not AssemblyOrderStatus.OPEN:
            continue
        if order.machine_code != machine_code:
            continue
        if exclude_order_id is not None and order.order_id == exclude_order_id:
            continue
        for line in order.lines:
            occupied.add(line.catalog_code)
    for code in candidate_codes:
        normalized = code.strip()
        if normalized in occupied:
            return DuplicateCatalogCode(catalog_code=normalized)
    return None


@beartype
def reserved_qty_by_catalog_code(
    open_orders: tuple[MicromarketAssemblyOrder, ...],
) -> Mapping[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for order in open_orders:
        if order.status is not AssemblyOrderStatus.OPEN:
            continue
        for line in order.lines:
            totals[line.catalog_code] = totals.get(line.catalog_code, Decimal("0")) + line.qty
    return totals
