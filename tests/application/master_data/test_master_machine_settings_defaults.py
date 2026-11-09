from __future__ import annotations

from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.domain.ids import MachineId


def test_master_machine_settings_defaults_true() -> None:
    machine = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )
    assert machine.include_in_no_sales_monitoring is True
    assert machine.create_visit_on_no_sales is True


def test_master_machine_review_participation_defaults_true() -> None:
    machine = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )
    assert machine.include_in_visit_photo_review is True
