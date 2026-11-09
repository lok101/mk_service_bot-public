from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    MasterLocation,
    MasterPlacement,
)
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.visit_board_lookups import (
    MasterLocationDisplayLookup,
    MasterPlacementAtLookup,
)

_MACHINE = MachineId("101")
_BOUNDARY = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def test_location_display_for_id() -> None:
    stores = InMemoryMasterDataStores()
    stores.locations.upsert(
        MasterLocation(
            location_id="1",
            name="БЦ Север",
            city="Город",
            street="ул. Ленина",
            house="1",
            display_name="БЦ Север | ул. Ленина, 1",
            latitude=None,
            longitude=None,
        )
    )
    lookup = MasterLocationDisplayLookup(stores.locations)

    found = lookup.display_for("1")

    assert found is not None
    assert found.location_id == "1"
    assert found.display_name == "БЦ Север | ул. Ленина, 1"
    assert found.address == "ул. Ленина, 1"
    assert lookup.display_for("404") is None


def test_master_placement_at_lookup_adapter() -> None:
    stores = InMemoryMasterDataStores()
    stores.placements.insert(
        MasterPlacement(
            placement_id="p1",
            machine_id=_MACHINE,
            location_id="1",
            valid_from=datetime(2026, 7, 1, tzinfo=UTC),
            valid_to=_BOUNDARY,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p2",
            machine_id=_MACHINE,
            location_id="2",
            valid_from=_BOUNDARY,
            valid_to=None,
        )
    )
    lookup = MasterPlacementAtLookup(stores.placements)

    snapshots = lookup.placements_for_machine(_MACHINE)

    assert [item.location_id for item in snapshots] == ["1", "2"]
    assert snapshots[0].valid_to == _BOUNDARY
    assert snapshots[1].valid_to is None
    assert lookup.placements_for_machine(MachineId("999")) == ()
