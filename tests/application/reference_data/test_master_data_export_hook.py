from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


class _BoomExport:
    def export_all(self, stores: object) -> None:
        raise RuntimeError("sheets down")


def test_export_failure_keeps_domain() -> None:
    stores = InMemoryMasterDataStores()
    result = InstallMachineAtLocation(
        stores=stores,
        now_factory=lambda: _NOW,
        export_hook=_BoomExport(),
    ).execute(
        InstallMachineAtLocationInput(
            name="A",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    assert stores.machines.get(result.machine_id) is not None
