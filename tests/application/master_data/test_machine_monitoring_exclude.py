from __future__ import annotations

from src.application.master_data import machine_ids_excluded_from_no_sales_monitoring
from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.domain.ids import MachineId


def test_machine_ids_excluded_from_flag_false() -> None:
    machines = (
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
            include_in_no_sales_monitoring=False,
        ),
        MasterMachine(
            machine_id=MachineId("102"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
            include_in_no_sales_monitoring=True,
        ),
    )
    assert machine_ids_excluded_from_no_sales_monitoring(machines) == frozenset({"101"})
