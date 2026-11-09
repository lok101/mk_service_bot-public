from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.application.master_data import InMemoryMasterDataStores
from src.application.master_data.models import (
    LOCATION_COUNTER_KEY,
    MasterLocation,
    MasterPlacement,
)
from src.application.master_data.reconcile_location_ids import (
    apply_location_id_remap,
    load_locations_directory_csv_rows,
    reconcile_location_ids,
)
from src.domain.ids import MachineId

_DIR_HEADER = [
    "Id",
    "Создание",
    "Снятие",
    "Id торговой точки",
    "Название",
    "Полное имя",
    "Город",
    "Улица",
    "Дом",
    "Широта",
    "Долгота",
]


def _csv_rows(*data_rows: list[str]) -> list[list[str]]:
    return [_DIR_HEADER, *data_rows]


def _seed_domain_with_wrong_ids(stores: InMemoryMasterDataStores) -> None:
    stores.locations.upsert(
        MasterLocation(
            location_id="1",
            name="",
            city="",
            street="",
            house="",
            display_name="Школа полн",
            latitude=Decimal("55.75"),
            longitude=Decimal("37.62"),
        ),
    )
    stores.locations.upsert(
        MasterLocation(
            location_id="2",
            name="",
            city="",
            street="",
            house="",
            display_name="Старая",
            latitude=None,
            longitude=None,
        ),
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-open",
            machine_id=MachineId("101"),
            location_id="1",
            valid_from=datetime(2024, 1, 1, tzinfo=UTC),
            valid_to=None,
        ),
    )
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-closed",
            machine_id=MachineId("101"),
            location_id="2",
            valid_from=datetime(2023, 1, 1, tzinfo=UTC),
            valid_to=datetime(2023, 12, 31, tzinfo=UTC),
        ),
    )
    stores.counters.set(LOCATION_COUNTER_KEY, 2)


def test_reconcile_builds_remap_from_csv_canonical_ids() -> None:
    stores = InMemoryMasterDataStores()
    _seed_domain_with_wrong_ids(stores)
    csv_rows = _csv_rows(
        [
            "101",
            "01.01.2024",
            "",
            "101",
            "",
            "Школа полн",
            "",
            "",
            "",
            "55,75",
            "37,62",
        ],
        [
            "99",
            "01.01.2023",
            "31.12.2023",
            "101",
            "",
            "Старая",
            "",
            "",
            "",
            "",
            "",
        ],
    )

    report = reconcile_location_ids(stores, csv_rows=csv_rows)

    assert report.ok is True
    assert report.location_id_remap == {"1": "101", "2": "99"}


def test_apply_location_id_remap_updates_locations_and_placements() -> None:
    stores = InMemoryMasterDataStores()
    _seed_domain_with_wrong_ids(stores)
    remap = {"1": "101", "2": "99"}

    changed = apply_location_id_remap(stores, remap)

    assert changed == 2
    assert stores.locations.get("101") is not None
    assert stores.locations.get("99") is not None
    assert stores.locations.get("1") is None
    open_placement = stores.placements.get_open(MachineId("101"))
    assert open_placement is not None
    assert open_placement.location_id == "101"
    history = stores.placements.list_for_machine(MachineId("101"))
    closed = next(item for item in history if item.valid_to is not None)
    assert closed.location_id == "99"
    assert stores.counters.get(LOCATION_COUNTER_KEY) == 101


def test_reconcile_reports_name_mismatch_without_blocking() -> None:
    stores = InMemoryMasterDataStores()
    _seed_domain_with_wrong_ids(stores)
    csv_rows = _csv_rows(
        [
            "101",
            "01.01.2024",
            "",
            "101",
            "",
            "Другое имя",
            "",
            "",
            "",
            "55,75",
            "37,62",
        ],
        [
            "99",
            "01.01.2023",
            "31.12.2023",
            "101",
            "",
            "Старая",
            "",
            "",
            "",
            "",
            "",
        ],
    )

    report = reconcile_location_ids(stores, csv_rows=csv_rows)

    assert report.ok is True
    assert len(report.name_mismatches) == 1
    assert report.name_mismatches[0].csv_name == "Другое имя"


def test_reconcile_fails_on_extra_domain_without_flag() -> None:
    stores = InMemoryMasterDataStores()
    _seed_domain_with_wrong_ids(stores)
    stores.placements.insert(
        MasterPlacement(
            placement_id="p-extra",
            machine_id=MachineId("501"),
            location_id="3",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        ),
    )
    stores.locations.upsert(
        MasterLocation(
            location_id="3",
            name="",
            city="",
            street="",
            house="",
            display_name="Новая",
            latitude=None,
            longitude=None,
        ),
    )
    csv_rows = _csv_rows(
        [
            "101",
            "01.01.2024",
            "",
            "101",
            "",
            "Школа полн",
            "",
            "",
            "",
            "55,75",
            "37,62",
        ],
        [
            "99",
            "01.01.2023",
            "31.12.2023",
            "101",
            "",
            "Старая",
            "",
            "",
            "",
            "",
            "",
        ],
    )

    report = reconcile_location_ids(stores, csv_rows=csv_rows)

    assert report.ok is False
    assert report.extra_domain_keys
    assert any("domain placement missing in csv" in error for error in report.errors)


def test_reconcile_tolerates_small_coordinate_drift() -> None:
    from src.application.master_data.reconcile_location_ids import _coordinates_match

    assert _coordinates_match(Decimal("56.829433"), Decimal("56.829432")) is True
    assert _coordinates_match(Decimal("56.829433"), Decimal("56.829400")) is False


def test_load_locations_directory_csv_reads_utf8_sig(tmp_path: Path) -> None:
    path = tmp_path / "locations.csv"
    path.write_text(
        "Id;Создание;Снятие;Id торговой точки;Название;Полное имя\n101;01.01.2024;;101;;Школа\n",
        encoding="utf-8-sig",
    )
    rows = load_locations_directory_csv_rows(path)
    assert rows[0][0] == "Id"
    assert rows[1][0] == "101"
