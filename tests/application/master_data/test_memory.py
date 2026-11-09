from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.master_data import InMemoryMasterDataStores
from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
    OpenPlacementExists,
)
from src.domain.ids import MachineId

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_memory_location_machine_roundtrip() -> None:
    stores = InMemoryMasterDataStores()
    loc = MasterLocation(
        location_id="1",
        name="Точка А",
        city="Город",
        street="ул. 1",
        house="1",
        display_name="Точка А | ул. 1, 1",
        latitude=Decimal("55.75"),
        longitude=Decimal("37.62"),
    )
    machine = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )
    stores.locations.upsert(loc)
    stores.machines.upsert(machine)
    assert stores.locations.get("1") == loc
    assert stores.machines.get(MachineId("101")) == machine
    assert stores.locations.is_empty() is False


def test_memory_placement_open_roundtrip() -> None:
    stores = InMemoryMasterDataStores()
    placement = MasterPlacement(
        placement_id="p1",
        machine_id=MachineId("101"),
        location_id="1",
        valid_from=_NOW,
        valid_to=None,
    )
    stores.placements.insert(placement)
    assert stores.placements.get_open(MachineId("101")) == placement
    assert stores.placements.list_for_machine(MachineId("101")) == (placement,)


def test_reject_second_open_placement_for_machine() -> None:
    stores = InMemoryMasterDataStores()
    stores.placements.insert(
        MasterPlacement(
            placement_id="p1",
            machine_id=MachineId("101"),
            location_id="1",
            valid_from=_NOW,
            valid_to=None,
        )
    )
    with pytest.raises(OpenPlacementExists):
        stores.placements.insert(
            MasterPlacement(
                placement_id="p2",
                machine_id=MachineId("101"),
                location_id="2",
                valid_from=_NOW,
                valid_to=None,
            )
        )
