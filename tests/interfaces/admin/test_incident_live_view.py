from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
)
from src.domain.ids import MachineId
from src.interfaces.admin.incident_live_view import incident_machine_screen_name

_OPENED = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def test_incident_machine_screen_name_uses_location_display_name() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("174"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    stores.locations.upsert(
        MasterLocation(
            location_id="loc-1",
            name="",
            city="",
            street="",
            house="",
            display_name="Школа 12",
            latitude=None,
            longitude=None,
        )
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-1",
            machine_id=MachineId("174"),
            location_id="loc-1",
            valid_from=_OPENED,
            valid_to=None,
        )
    )
    assert incident_machine_screen_name(stores, "174") == "Школа 12"


def test_incident_machine_screen_name_blank_when_only_code_is_known() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("174"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    assert incident_machine_screen_name(stores, "174") == "—"
    assert incident_machine_screen_name(None, "174") == "—"
