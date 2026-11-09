from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.sheets.locations_directory import (
    LocationPlacement,
    LocationsDirectorySnapshot,
)
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.composition.wiring.sales_monitoring_worker_adapters import (
    ReferenceDataTechnicianDisplayLookup,
    _catalog_from_provider,
)
from src.infrastructure.composition.wiring.wire_sales_sheet_export import (
    _machine_names_from_provider,
)

_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_COFFEE_ROW = ["129", "Cafe", "Tech", "T1"]
_SNACK_ROW = ["501", "Snack Loc", "Tech", "T1"]
_SNACK_ONLY_ROW = ["502", "Snack Only", "SnackTech", "T2"]


def test_export_machine_names_use_locations_catalog() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, [_HEADER, _COFFEE_ROW])
    provider.apply_rows(ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS, [_HEADER, _SNACK_ROW])
    names = _machine_names_from_provider(provider)
    assert MachineId("501") in names
    assert MachineId("129") in names


def test_export_machine_names_include_open_directory_micromarket() -> None:
    """Without a hydrate micromarket snapshot, open directory fills the display name."""
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, [_HEADER, _COFFEE_ROW])
    micromarket = LocationPlacement(
        location_id="loc-mm",
        machine_id=MachineId("701"),
        installed_on=date(2026, 9, 1),
        removed_on=None,
        name="Теплицы, столовая",
        latitude=None,
        longitude=None,
    )
    removed = LocationPlacement(
        location_id="loc-old",
        machine_id=MachineId("799"),
        installed_on=date(2025, 1, 1),
        removed_on=date(2026, 1, 1),
        name="Снятый",
        latitude=Decimal("0"),
        longitude=Decimal("0"),
    )
    # Catalog name must win over a conflicting directory label for coffee.
    coffee_dir = LocationPlacement(
        location_id="loc-129",
        machine_id=MachineId("129"),
        installed_on=date(2026, 1, 1),
        removed_on=None,
        name="Directory override must not win",
        latitude=None,
        longitude=None,
    )
    provider.apply_master_snapshots(
        coffee=None,
        snack=None,
        locations_directory=LocationsDirectorySnapshot(
            placements=(micromarket, removed, coffee_dir),
            by_location_id={
                "loc-mm": micromarket,
                "loc-old": removed,
                "loc-129": coffee_dir,
            },
        ),
    )
    names = _machine_names_from_provider(provider)
    assert names[MachineId("701")] == "Теплицы, столовая"
    assert MachineId("799") not in names
    assert names[MachineId("129")] == "Cafe"


def test_sm_catalog_uses_coffee_locations() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, [_HEADER, _COFFEE_ROW])
    provider.apply_rows(ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS, [_HEADER, _SNACK_ROW])
    catalog = _catalog_from_provider(provider)
    ids = {row.machine_id.value for row in catalog}
    assert ids == {"129"}
    assert all(row.machine_id.value != "501" for row in catalog)


def test_sm_display_lookup_uses_directory() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["T2", "SnackTechDir"]],
    )
    lookup = ReferenceDataTechnicianDisplayLookup(provider=provider)
    assert lookup.display_name(TechnicianId("T2")) == "SnackTechDir"


def test_sm_catalog_technician_display_from_directory() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, ["129", "Cafe", "LocationsName", "T1"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["T1", "DirectoryName"]],
    )
    catalog = _catalog_from_provider(provider)
    assert len(catalog) == 1
    assert catalog[0].assigned_technician_display == "DirectoryName"


def test_sm_display_lookup_skips_snack_only_technician() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, [_HEADER, _COFFEE_ROW])
    provider.apply_rows(
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        [_HEADER, _SNACK_ONLY_ROW],
    )
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [["Id", "Имя"], ["T1", "Tech"]],
    )
    lookup = ReferenceDataTechnicianDisplayLookup(provider=provider)
    assert lookup.display_name(TechnicianId("T2")) is None
    assert lookup.display_name(TechnicianId("T1")) == "Tech"
