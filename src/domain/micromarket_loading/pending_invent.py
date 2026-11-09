from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class PendingMicromarketInvent:
    """Accepted invent ``now`` snapshot before ``apply_inventory`` (post-visit squeeze)."""

    machine_code: str
    inventory_id: str
    quantities: tuple[tuple[str, Decimal], ...]
    submitted_at: datetime
    operational_day: date
    performed_technician_id: str = ""
    performed_technician_name: str = ""
    assigned_technician_id: str = ""
    assigned_technician_name: str = ""
    machine_name: str = ""

    def __post_init__(self) -> None:
        if not self.machine_code.strip():
            raise ValueError("machine_code must be non-empty")
        if not self.inventory_id.strip():
            raise ValueError("inventory_id must be non-empty")
        codes = [code for code, _ in self.quantities]
        if len(codes) != len(set(codes)):
            raise ValueError("quantities must not contain duplicate product codes")

    @beartype
    def quantity_map(self) -> dict[str, Decimal]:
        return {code: qty for code, qty in self.quantities}
