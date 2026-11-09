from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.inventory_reconciliation.company_occupancy import MachineCompanyOccupancy
from src.domain.ids import MachineId
from src.infrastructure.mongodb.machine_company_occupancy import (
    MongoMachineCompanyOccupancyStore,
)

_MACHINE = MachineId("vm-01")
_T1 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def test_mongo_occupancy_replace_roundtrip() -> None:
    collection = mongomock.MongoClient().db.occ
    store = MongoMachineCompanyOccupancyStore.from_collection(collection)
    store.replace_for_machine(
        _MACHINE,
        (
            MachineCompanyOccupancy(
                machine_id=_MACHINE,
                company_id=1,
                valid_from=_T1,
                valid_to=_T2,
            ),
            MachineCompanyOccupancy(
                machine_id=_MACHINE,
                company_id=2,
                valid_from=_T2,
                valid_to=None,
            ),
        ),
    )
    loaded = store.list_for_machine(_MACHINE)
    assert len(loaded) == 2
    assert loaded[0].company_id == 1
    assert loaded[0].valid_to == _T2
    assert loaded[1].company_id == 2
    assert loaded[1].valid_to is None


def test_mongo_occupancy_replace_clears_previous() -> None:
    collection = mongomock.MongoClient().db.occ
    store = MongoMachineCompanyOccupancyStore.from_collection(collection)
    store.replace_for_machine(
        _MACHINE,
        (
            MachineCompanyOccupancy(
                machine_id=_MACHINE,
                company_id=1,
                valid_from=_T1,
                valid_to=None,
            ),
        ),
    )
    store.replace_for_machine(_MACHINE, ())
    assert store.list_for_machine(_MACHINE) == ()
