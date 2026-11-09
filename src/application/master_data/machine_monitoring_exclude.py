from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.master_data.models import MasterMachine


@beartype
def machine_ids_excluded_from_no_sales_monitoring(
    machines: Sequence[MasterMachine],
) -> frozenset[str]:
    return frozenset(
        machine.machine_id.value
        for machine in machines
        if not machine.include_in_no_sales_monitoring
    )
