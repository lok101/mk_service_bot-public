from __future__ import annotations

from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.domain.ids import MachineId
from src.infrastructure.reference_data.master_machine_no_sales_visit_policy import (
    MasterMachineNoSalesVisitPolicy,
)


def test_master_machine_policy_reads_flag() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
            create_visit_on_no_sales=False,
        )
    )
    policy = MasterMachineNoSalesVisitPolicy(stores.machines)
    assert policy.allows_create_visit_on_no_sales(MachineId("101")) is False
    assert policy.allows_create_visit_on_no_sales(MachineId("999")) is True
