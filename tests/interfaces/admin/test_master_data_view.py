from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
)
from src.interfaces.admin.master_data_view import build_master_machines_view

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_build_master_machines_view_includes_company_name() -> None:
    stores = InMemoryMasterDataStores()
    installed = InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    mid = installed.machine_id
    view = build_master_machines_view(
        stores,
        company_names={mid: "Орлов М.О."},
    )
    assert len(view.rows) == 1
    assert view.rows[0].company_name == "Орлов М.О."
    assert view.rows[0].machine_id == mid.value


def test_build_master_machines_view_empty_company_when_missing() -> None:
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="ул. 1",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    view = build_master_machines_view(stores, company_names={})
    assert len(view.rows) == 1
    assert view.rows[0].company_name == ""
