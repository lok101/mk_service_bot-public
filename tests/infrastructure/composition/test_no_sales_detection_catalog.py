from __future__ import annotations

from src.application.sales_monitoring.run_sales_report import CatalogMachine
from src.domain.ids import MachineId
from src.infrastructure.composition.wiring.no_sales_detection_catalog import (
    NoSalesParkMachine,
    merge_no_sales_detection_catalog,
    status_board_catalog,
)

_COFFEE = CatalogMachine(
    machine_id=MachineId("101"),
    name="Кофе",
    assigned_technician_id=None,
    assigned_technician_display=None,
)


def test_detection_catalog_includes_active_snack_and_micro_market() -> None:
    catalog = merge_no_sales_detection_catalog(
        (_COFFEE,),
        (
            NoSalesParkMachine(MachineId("501"), "snack", "active_on_site", "Снек"),
            NoSalesParkMachine(MachineId("701"), "micro_market", "active_on_site", "Холод"),
        ),
    )
    assert [item.machine_id.value for item in catalog] == ["101", "501", "701"]


def test_detection_catalog_skips_storage_and_master_coffee() -> None:
    catalog = merge_no_sales_detection_catalog(
        (_COFFEE,),
        (
            NoSalesParkMachine(MachineId("502"), "snack", "in_storage", "Склад"),
            NoSalesParkMachine(MachineId("102"), "coffee", "active_on_site", "Только парк"),
        ),
    )
    assert [item.machine_id.value for item in catalog] == ["101"]


def test_detection_catalog_keeps_coffee_row_when_ids_match() -> None:
    catalog = merge_no_sales_detection_catalog(
        (_COFFEE,),
        (NoSalesParkMachine(MachineId("101"), "snack", "active_on_site", "Чужое имя"),),
    )
    assert catalog == (_COFFEE,)


def test_status_board_catalog_stays_coffee_locations() -> None:
    coffee = (_COFFEE,)
    assert status_board_catalog(coffee) is coffee
