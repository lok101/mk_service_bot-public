from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
    hydrate_provider_from_master_data,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.infrastructure.composition.adapters.period_party_names import (
    VendingMachinePeriodPartyNamesLookup,
)
from src.infrastructure.integrations.google.sheets.vending_machine_repository import (
    GoogleSheetsVendingMachineRepository,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_party_names_uses_location_when_master_enabled() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Точка Live",
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
    repo = GoogleSheetsVendingMachineRepository(provider=provider)
    lookup = VendingMachinePeriodPartyNamesLookup(machines=repo)
    assert lookup.location_name(installed.machine_id) == "Точка Live | a, 1"
