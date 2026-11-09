from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    InMemoryMasterDataStores,
    MasterDataCommandRejected,
    UpdateMachineSettings,
    UpdateMachineSettingsInput,
)
from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterMachine,
)
from src.domain.ids import MachineId

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def test_update_machine_settings_persists_flags() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    UpdateMachineSettings(stores=stores, now_factory=lambda: _NOW).execute(
        UpdateMachineSettingsInput(
            machine_id=MachineId("101"),
            include_in_no_sales_monitoring=False,
            create_visit_on_no_sales=False,
            include_in_visit_photo_review=True,
            actor_telegram_user_id=1,
        )
    )
    saved = stores.machines.get(MachineId("101"))
    assert saved is not None
    assert saved.include_in_no_sales_monitoring is False
    assert saved.create_visit_on_no_sales is False


def test_update_machine_settings_unknown_rejects() -> None:
    stores = InMemoryMasterDataStores()
    try:
        UpdateMachineSettings(stores=stores, now_factory=lambda: _NOW).execute(
            UpdateMachineSettingsInput(
                machine_id=MachineId("999"),
                include_in_no_sales_monitoring=True,
                create_visit_on_no_sales=True,
                include_in_visit_photo_review=True,
                actor_telegram_user_id=1,
            )
        )
    except MasterDataCommandRejected as exc:
        assert exc.code == "machine_not_found"
    else:
        raise AssertionError("expected reject")


def test_update_machine_settings_writes_audit() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    UpdateMachineSettings(stores=stores, now_factory=lambda: _NOW).execute(
        UpdateMachineSettingsInput(
            machine_id=MachineId("101"),
            include_in_no_sales_monitoring=False,
            create_visit_on_no_sales=True,
            include_in_visit_photo_review=True,
            actor_telegram_user_id=42,
        )
    )
    records = stores.audit.list_all()
    assert any(
        r.command == "update_machine_settings" and r.actor_telegram_user_id == 42 for r in records
    )


def test_update_machine_settings_persists_review_participation() -> None:
    stores = InMemoryMasterDataStores()
    stores.machines.upsert(
        MasterMachine(
            machine_id=MachineId("101"),
            kind=MachineKind.COFFEE,
            status=MachineStatus.ACTIVE_ON_SITE,
            label=None,
        )
    )
    UpdateMachineSettings(stores=stores, now_factory=lambda: _NOW).execute(
        UpdateMachineSettingsInput(
            machine_id=MachineId("101"),
            include_in_no_sales_monitoring=True,
            create_visit_on_no_sales=True,
            include_in_visit_photo_review=False,
            actor_telegram_user_id=1,
        )
    )
    saved = stores.machines.get(MachineId("101"))
    assert saved is not None
    assert saved.include_in_visit_photo_review is False
    assert saved.include_in_no_sales_monitoring is True
    record = stores.audit.list_all()[-1]
    assert record.payload["include_in_visit_photo_review"] == "False"
