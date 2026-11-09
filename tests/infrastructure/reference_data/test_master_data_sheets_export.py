from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.application.master_data import (
    InMemoryMasterDataStores,
    InstallMachineAtLocation,
    InstallMachineAtLocationInput,
    MachineKind,
    MasterDataStores,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.domain.ids import MachineId
from src.infrastructure.reference_data.master_data_sheets_export import (
    GoogleSheetsMasterDataExport,
    MasterDataSheetTarget,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _stub_sheets_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.reference_data.master_data_sheets_export._get_rate_limiter",
        lambda: limiter,
    )


def test_master_data_sheets_export_acquires_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.reference_data.master_data_sheets_export._get_rate_limiter",
        lambda: limiter,
    )
    export = GoogleSheetsMasterDataExport(
        service_factory=lambda: (_ for _ in ()).throw(AssertionError("no api")),
        locations=MasterDataSheetTarget("mirror-book", 11),
        machines=MasterDataSheetTarget("mirror-book", 12),
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names_provider=lambda _stores: {},
    )
    with pytest.raises(AssertionError):
        export._replace_sheet(MasterDataSheetTarget("mirror-book", 11), [["hdr"]])
    limiter.acquire.assert_called()


def test_google_sheets_export_uses_mirror_targets_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_replace(
        self: GoogleSheetsMasterDataExport,
        target: MasterDataSheetTarget,
        rows: object,
    ) -> None:
        del self, rows
        calls.append((target.spreadsheet_id, target.sheet_id))

    monkeypatch.setattr(GoogleSheetsMasterDataExport, "_replace_sheet", fake_replace)
    export = GoogleSheetsMasterDataExport(
        service_factory=lambda: None,
        locations=MasterDataSheetTarget("mirror-book", 11),
        machines=MasterDataSheetTarget("mirror-book", 12),
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names_provider=lambda _stores: {},
    )
    export.export_all(InMemoryMasterDataStores())
    assert calls == [("mirror-book", 11), ("mirror-book", 12)]


def test_google_sheets_export_machines_company_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[list[str]]] = {}

    def fake_replace(
        self: GoogleSheetsMasterDataExport,
        target: MasterDataSheetTarget,
        rows: object,
    ) -> None:
        del self
        if target.sheet_id == 12:
            captured["machines"] = [list(row) for row in rows]  # type: ignore[arg-type]

    monkeypatch.setattr(GoogleSheetsMasterDataExport, "_replace_sheet", fake_replace)
    stores = InMemoryMasterDataStores()
    InstallMachineAtLocation(stores=stores, now_factory=lambda: _NOW).execute(
        InstallMachineAtLocationInput(
            name="Кафе",
            city="Город",
            street="a",
            house="1",
            latitude=None,
            longitude=None,
            kind=MachineKind.COFFEE,
            actor_telegram_user_id=1,
        )
    )
    mid = stores.machines.list_all()[0].machine_id

    def provider(_stores: MasterDataStores) -> dict[MachineId, str]:
        return {mid: "Орлов М.О."}

    export = GoogleSheetsMasterDataExport(
        service_factory=lambda: None,
        locations=MasterDataSheetTarget("mirror-book", 11),
        machines=MasterDataSheetTarget("mirror-book", 12),
        roster=InMemoryLocationRosterStore(),
        technician_names={},
        company_names_provider=provider,
    )
    export.export_all(stores)
    machine_rows = captured["machines"]
    assert machine_rows[0][-1] == "Компания"
    assert machine_rows[1][-1] == "Орлов М.О."
