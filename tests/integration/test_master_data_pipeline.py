from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
    RelocateMachine,
    RelocateMachineInput,
    hydrate_provider_from_master_data,
)
from src.application.reference_data.provider import ReferenceDataProvider

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


def test_install_relocate_provider_history() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Старая",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    provider = ReferenceDataProvider()
    hydrate_provider_from_master_data(provider, stores)
    before = next(
        m for m in provider.locations_catalog().unassigned_machines if m.id == installed.machine_id
    )
    assert before.name == "Старая | a, 1"

    RelocateMachine(stores=stores, now_factory=lambda: _LATER).execute(
        RelocateMachineInput(
            machine_id=installed.machine_id,
            name="Новая",
            city="Город",
            street="b",
            house="1",
            latitude=None,
            longitude=None,
            actor_telegram_user_id=1,
        )
    )
    hydrate_provider_from_master_data(provider, stores)
    after = next(
        m for m in provider.locations_catalog().unassigned_machines if m.id == installed.machine_id
    )
    assert after.name == "Новая | b, 1"
    history = stores.placements.list_for_machine(installed.machine_id)
    assert len(history) == 2
    assert sum(1 for p in history if p.valid_to is None) == 1
