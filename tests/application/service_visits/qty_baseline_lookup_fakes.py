from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from beartype import beartype

from src.domain.ids import MachineId


@beartype
@dataclass
class FakeMachineSalesQtyBaselineLookup:
    result: Decimal | None = None
    calls: list[tuple[MachineId, date]] = field(default_factory=list)

    @beartype
    def baseline_avg_qty(
        self,
        *,
        machine_id: MachineId,
        as_of_day: date,
    ) -> Decimal | None:
        self.calls.append((machine_id, as_of_day))
        return self.result
