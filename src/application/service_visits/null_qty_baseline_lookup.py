from __future__ import annotations

from datetime import date
from decimal import Decimal

from beartype import beartype

from src.domain.ids import MachineId


@beartype
class NullMachineSalesQtyBaselineLookup:
    @beartype
    def baseline_avg_qty(
        self,
        *,
        machine_id: MachineId,
        as_of_day: date,
    ) -> Decimal | None:
        return None
