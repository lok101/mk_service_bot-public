from __future__ import annotations

from collections.abc import Mapping, Sequence

from beartype import beartype

from src.application.inventory_reconciliation import (
    MachineCompanyOccupancyStore,
    resolve_current_company_name,
)
from src.domain.ids import MachineId


@beartype
def build_machine_company_names(
    *,
    occupancy_store: MachineCompanyOccupancyStore,
    display_names: Mapping[int, str],
    machine_ids: Sequence[MachineId],
) -> dict[MachineId, str]:
    return {
        machine_id: resolve_current_company_name(
            occupancy_store.list_for_machine(machine_id),
            display_names,
        )
        for machine_id in machine_ids
    }
