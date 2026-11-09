from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.reference_data.errors import ReferenceDataUnavailable
from src.application.reference_data.models import (
    APP_REFERENCE_DATA_SOURCE_IDS,
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.sheets import TechnicianLocationsSnapshot, list_all_machines_from_snapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]
_COFFEE_ROW = ["129", "Cafe", "Tech", "T1"]
_SNACK_ROW = ["501", "Snack Loc", "Tech", "T1"]
_DIR_HEADER = ["Id", "Имя"]
_DIR_ROW = ["10003", "Данил"]
_LOC_HEADER = [
    "",
    "Создание",
    "Снятие",
    "ТТ",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]
_LOC_ROW = ["loc-a", "01.06.2026", "", "101", "короткое", "Кафе А", "", "", "", "55,8", "49,1"]
_NOW = datetime(2026, 7, 1, tzinfo=UTC)
_MS_NOW = datetime(2026, 7, 30, tzinfo=UTC)


class _FakeStore:
    def __init__(self, snapshots: dict[ReferenceDataSourceId, ReferenceDataSnapshot]) -> None:
        self._snapshots = snapshots

    def get(self, source_id: ReferenceDataSourceId) -> ReferenceDataSnapshot | None:
        return self._snapshots.get(source_id)

    def put(self, snapshot: ReferenceDataSnapshot) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_by_id(self, snapshot_id: str) -> ReferenceDataSnapshot | None:  # pragma: no cover
        return None

    def delete_by_id(self, snapshot_id: str) -> None:  # pragma: no cover
        return None

    def record_sync_error(self, source_id, message, at) -> None:  # pragma: no cover
        raise NotImplementedError


def test_apply_rows_populates_typed_snapshot() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS, [_HEADER, _ROW])
    snapshot = provider.coffee_locations()
    assert any(
        machine.name == "Локация 1"
        for machines in snapshot.machines_by_technician_id.values()
        for machine in machines
    )


def test_degraded_source_returns_none() -> None:
    provider = ReferenceDataProvider()
    assert provider.coffee_locations_or_none() is None
    assert provider.locations_catalog_or_none() is None


def test_strict_getter_raises_when_degraded() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ReferenceDataUnavailable):
        provider.coffee_locations()
    with pytest.raises(ReferenceDataUnavailable):
        provider.locations_catalog()


def test_hydrate_from_store_parses_raw_rows() -> None:
    snapshot = ReferenceDataSnapshot(
        source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        rows=(tuple(_HEADER), tuple(_ROW)),
        content_hash="sha256:x",
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )
    provider = ReferenceDataProvider()
    provider.hydrate_from_store(
        _FakeStore({ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS: snapshot}),
    )
    assert provider.coffee_locations_or_none() is not None


def test_hydrate_skips_broken_rows_without_crash() -> None:
    broken = ReferenceDataSnapshot(
        source_id=ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        rows=(("wrong", "header"),),
        content_hash="sha256:x",
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )
    provider = ReferenceDataProvider()
    provider.hydrate_from_store(
        _FakeStore({ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS: broken}),
    )
    assert provider.coffee_locations_or_none() is None


def test_has_source_reports_presence() -> None:
    provider = ReferenceDataProvider()
    assert provider.has_source(ReferenceDataSourceId.BOT_USERS) is False
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, _ROW],
    )
    assert provider.has_source(ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS) is True


def test_locations_catalog_merges_coffee_and_snack() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, _COFFEE_ROW],
    )
    provider.apply_rows(
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        [_HEADER, _SNACK_ROW],
    )
    catalog = provider.locations_catalog()
    ids = {m.id.value for m in list_all_machines_from_snapshot(catalog)}
    assert ids == {"129", "501"}


def test_coffee_locations_filters_snack_and_names() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, _COFFEE_ROW],
    )
    provider.apply_rows(
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        [_HEADER, ["501", "Snack Only", "SnackTech", "T2"]],
    )
    coffee = provider.coffee_locations()
    ids = {m.id.value for m in list_all_machines_from_snapshot(coffee)}
    assert ids == {"129"}
    assert "T2" not in {str(t.value) for t in coffee.technician_names_by_id}


def test_apply_coffee_rejects_snack_machine_id() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ValueError, match="(?i)snack"):
        provider.apply_rows(
            ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            [_HEADER, ["501", "X", "Tech", "T1"]],
        )


def test_apply_snack_rejects_non_snack_machine_id() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ValueError, match="(?i)snack"):
        provider.apply_rows(
            ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
            [_HEADER, ["129", "X", "Tech", "T1"]],
        )


def test_apply_snack_rejects_technician_name_conflict() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, _COFFEE_ROW],
    )
    with pytest.raises(ValueError, match="(?i)technician|name|conflict"):
        provider.apply_rows(
            ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
            [_HEADER, ["501", "Snack Loc", "Other Name", "T1"]],
        )


def test_apply_snack_rejects_empty_sheet() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ValueError, match="(?i)empty|no location"):
        provider.apply_rows(ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS, [_HEADER])


def test_apply_snack_collision_keeps_previous_snack_snapshot() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [_HEADER, _COFFEE_ROW],
    )
    provider.apply_rows(
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        [_HEADER, _SNACK_ROW],
    )
    with pytest.raises(ValueError):
        provider.apply_rows(
            ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
            [_HEADER, ["501", "Snack Loc", "Other Name", "T1"]],
        )
    names = {
        m.name
        for m in list_all_machines_from_snapshot(provider.locations_catalog())
        if m.id.value == "501"
    }
    assert names == {"Snack Loc"}


def test_locations_catalog_includes_machine_without_technician() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        [
            _HEADER,
            ["129", "Cafe", "Tech", "T1"],
            ["130", "No Tech Loc", "", ""],
        ],
    )
    ids = {m.id.value for m in list_all_machines_from_snapshot(provider.locations_catalog())}
    assert ids == {"129", "130"}


def test_apply_coffee_rejects_snack_id_without_technician() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ValueError, match="(?i)snack"):
        provider.apply_rows(
            ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
            [_HEADER, ["501", "Orphan Snack", "", ""]],
        )


def test_provider_vitrine_and_ms_catalog_are_separate() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_VITRINE,
        [["id", "имя"], ["sku1", "Сахар"]],
    )
    assert provider.product_vitrine_or_none() is not None
    assert provider.product_vitrine().lookup  # ParsedProductCatalog
    assert provider.product_catalog_or_none() is None


def test_sheets_rows_do_not_fill_product_catalog() -> None:
    """Sheets-витрина не должна попадать в product_catalog_* (MS-only API)."""
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_VITRINE,
        [["id", "имя"], ["sku1", "Сахар"]],
    )
    assert provider.product_catalog_or_none() is None


def test_hydrate_loads_ms_product_catalog() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    rows = (("code", "name", "entity_kind"), ("c1", "N", "product"))
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
            rows=rows,
            content_hash=compute_content_hash(rows),
            last_fetched_at=_MS_NOW,
            content_updated_at=_MS_NOW,
        ),
    )
    provider = ReferenceDataProvider()
    provider.hydrate_from_store(store)
    assert provider.product_catalog_or_none() is not None
    assert provider.product_catalog().by_code["c1"].name == "N"


def test_app_source_ids_contain_technicians_directory() -> None:
    assert ReferenceDataSourceId.TECHNICIANS_DIRECTORY in APP_REFERENCE_DATA_SOURCE_IDS
    assert ReferenceDataSourceId.TECHNICIANS_DIRECTORY.value == "technicians_directory"


def test_apply_technicians_directory() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        [_DIR_HEADER, _DIR_ROW],
    )
    snap = provider.technicians_directory()
    assert snap.names_by_id[TechnicianId("10003")] == "Данил"
    assert provider.has_source(ReferenceDataSourceId.TECHNICIANS_DIRECTORY)


def test_technicians_directory_strict_raises() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ReferenceDataUnavailable):
        provider.technicians_directory()
    assert provider.technicians_directory_or_none() is None


def test_apply_locations_directory() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.LOCATIONS_DIRECTORY,
        [_LOC_HEADER, _LOC_ROW],
    )
    snap = provider.locations_directory()
    assert snap.by_location_id["loc-a"].machine_id == MachineId("101")
    assert snap.by_location_id["loc-a"].name == "Кафе А"
    assert provider.has_source(ReferenceDataSourceId.LOCATIONS_DIRECTORY)


def test_locations_directory_strict_raises() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ReferenceDataUnavailable):
        provider.locations_directory()
    assert provider.locations_directory_or_none() is None
    assert provider.has_source(ReferenceDataSourceId.LOCATIONS_DIRECTORY) is False


def test_hydrate_from_store_loads_locations_directory() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    rows = (_LOC_HEADER, _LOC_ROW)
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.LOCATIONS_DIRECTORY,
            rows=tuple(tuple(cell) for cell in rows),
            content_hash=compute_content_hash(rows),
            last_fetched_at=_MS_NOW,
            content_updated_at=_MS_NOW,
        ),
    )
    provider = ReferenceDataProvider()
    provider.hydrate_from_store(store)
    assert provider.locations_directory_or_none() is not None
    assert provider.locations_directory().by_location_id["loc-a"].name == "Кафе А"


def _machine_snap(
    machine_id: str,
    *,
    name: str,
    tech_id: str | None = None,
    tech_name: str | None = None,
    weekdays: frozenset[int] = frozenset(),
) -> TechnicianLocationsSnapshot:
    machine = VendingMachine(
        id=MachineId(machine_id),
        name=name,
        service_weekdays=weekdays,
    )
    if tech_id is None:
        return TechnicianLocationsSnapshot(
            machines_by_technician_id={},
            technician_names_by_id={},
            unassigned_machines=(machine,),
        )
    technician_id = TechnicianId(tech_id)
    return TechnicianLocationsSnapshot(
        machines_by_technician_id={technician_id: (machine,)},
        technician_names_by_id={technician_id: tech_name or tech_id},
        unassigned_machines=(),
    )


def test_coffee_locations_excludes_micromarket_keeps_overlay_fields() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="T1", tech_name="Tech"),
        snack=_machine_snap("501", name="Snack", tech_id="T1", tech_name="Tech"),
        micromarket=_machine_snap("701", name="Fridge", tech_id="T1", tech_name="Tech"),
        locations_directory=None,
    )
    coffee = provider.coffee_locations()
    ids = {m.id.value for m in list_all_machines_from_snapshot(coffee)}
    assert ids == {"129"}
    assert "701" not in ids
    assert "501" not in ids


def test_coffee_locations_empty_snapshot_when_only_micromarket() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=None,
        snack=None,
        micromarket=_machine_snap("701", name="Fridge"),
        locations_directory=None,
    )
    coffee = provider.coffee_locations()
    assert list_all_machines_from_snapshot(coffee) == []
    assert coffee.technician_names_by_id == {}


def test_apply_master_snapshots_rejects_micromarket_duplicate_id() -> None:
    provider = ReferenceDataProvider()
    with pytest.raises(ValueError, match="(?i)duplicate|collision"):
        provider.apply_master_snapshots(
            coffee=_machine_snap("701", name="Cafe"),
            snack=None,
            micromarket=_machine_snap("701", name="Fridge"),
            locations_directory=None,
        )


def test_service_locations_includes_coffee_and_micromarket_excludes_snack() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="T1", tech_name="Tech"),
        snack=_machine_snap("501", name="Snack", tech_id="T2", tech_name="SnackTech"),
        micromarket=_machine_snap("701", name="Fridge", tech_id="T1", tech_name="Tech"),
        locations_directory=None,
    )
    service = provider.service_locations()
    ids = {m.id.value for m in list_all_machines_from_snapshot(service)}
    assert ids == {"129", "701"}
    assert "501" not in ids
    assert TechnicianId("T2") not in service.technician_names_by_id


def test_service_locations_when_micromarket_none_matches_coffee_ids() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap("129", name="Cafe", tech_id="T1", tech_name="Tech"),
        snack=_machine_snap("501", name="Snack", tech_id="T1", tech_name="Tech"),
        micromarket=None,
        locations_directory=None,
    )
    coffee_ids = {m.id.value for m in list_all_machines_from_snapshot(provider.coffee_locations())}
    service_ids = {
        m.id.value for m in list_all_machines_from_snapshot(provider.service_locations())
    }
    assert service_ids == coffee_ids == {"129"}


def test_service_locations_unavailable_when_no_catalog() -> None:
    provider = ReferenceDataProvider()
    assert provider.service_locations_or_none() is None
    with pytest.raises(ReferenceDataUnavailable):
        provider.service_locations()
