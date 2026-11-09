from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.micromarket_loading import MicromarketDeviceStock


def test_explicit_qty_sets_factual_and_last_factual_including_zero() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("5"), "2312": Decimal("0")},
        inventory_id="inv-fact-1",
        partial=True,
    )
    assert stock.qty("2311") == Decimal("5")
    assert stock.last_factual_qty("2311") == Decimal("5")
    assert stock.quantity_basis("2311") == "factual"
    assert stock.qty("2312") == Decimal("0")
    assert stock.last_factual_qty("2312") == Decimal("0")
    assert stock.quantity_basis("2312") == "factual"


def test_partial_omit_keeps_qty_and_last_factual_sets_virtual_and_records_anomaly() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4"), "2312": Decimal("2")},
        inventory_id="inv-base",
        partial=False,
    )
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("3")},
        inventory_id="inv-partial",
        partial=True,
    )
    assert stock.qty("2311") == Decimal("3")
    assert stock.quantity_basis("2311") == "factual"
    assert stock.last_factual_qty("2311") == Decimal("3")
    assert stock.qty("2312") == Decimal("2")
    assert stock.last_factual_qty("2312") == Decimal("2")
    assert stock.quantity_basis("2312") == "virtual"
    events = stock.pull_events()
    anomalies = [
        e
        for e in events
        if getattr(e, "kind", None) == "inventory_line_omitted" and e.product_code == "2312"
    ]
    assert len(anomalies) == 1
    assert anomalies[0].available_qty == Decimal("2")


def test_partial_omit_does_not_clear_last_factual_zero() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4"), "2312": Decimal("0")},
        inventory_id="inv-zero",
        partial=False,
    )
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4")},
        inventory_id="inv-omit-zero",
        partial=True,
    )
    assert stock.qty("2312") == Decimal("0")
    assert stock.last_factual_qty("2312") == Decimal("0")
    assert stock.quantity_basis("2312") == "virtual"
    events = stock.pull_events()
    omitted = [
        e
        for e in events
        if getattr(e, "kind", None) == "inventory_line_omitted" and e.product_code == "2312"
    ]
    assert omitted == []


def test_legacy_inventory_without_partial_replaces_entire_dict() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4"), "2312": Decimal("2")},
        inventory_id="inv-a",
    )
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("1")},
        inventory_id="inv-b",
    )
    assert stock.qty("2311") == Decimal("1")
    assert stock.qty("2312") == Decimal("0")
    assert stock.last_factual_qty("2312") is None
    assert stock.quantity_basis("2312") is None
    assert stock.quantity_basis("2311") == "factual"
    assert stock.last_factual_qty("2311") == Decimal("1")


def test_sale_sets_virtual_basis_without_clearing_last_factual() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
        quantities={"2311": Decimal("5")},
        inventory_id="inv-1",
    )
    stock.apply_sale_deduct(
        sale_source_id="sale-1",
        product_code="2311",
        qty=Decimal("2"),
        occurred_at=datetime(2026, 10, 1, 13, 0, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("3")
    assert stock.last_factual_qty("2311") == Decimal("5")
    assert stock.quantity_basis("2311") == "virtual"
    stock.apply_sale_deduct(
        sale_source_id="sale-2",
        product_code="2311",
        qty=Decimal("3"),
        occurred_at=datetime(2026, 10, 1, 14, 0, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("0")
    assert stock.last_factual_qty("2311") == Decimal("5")
    assert stock.quantity_basis("2311") == "virtual"


def test_rehydrate_matches_partial_inventory_fact_and_virtual() -> None:
    machine = "701"
    stock = MicromarketDeviceStock(machine_code=machine)
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4"), "2312": Decimal("2")},
        inventory_id="inv-a",
    )
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("3")},
        inventory_id="inv-b",
        partial=True,
    )
    expected_qty_2311 = stock.qty("2311")
    expected_qty_2312 = stock.qty("2312")
    expected_last_2311 = stock.last_factual_qty("2311")
    expected_last_2312 = stock.last_factual_qty("2312")
    expected_basis_2311 = stock.quantity_basis("2311")
    expected_basis_2312 = stock.quantity_basis("2312")
    events = stock.pull_events()
    rebuilt = MicromarketDeviceStock.rehydrate(machine_code=machine, events=events)
    assert rebuilt.qty("2311") == expected_qty_2311 == Decimal("3")
    assert rebuilt.qty("2312") == expected_qty_2312 == Decimal("2")
    assert rebuilt.last_factual_qty("2311") == expected_last_2311
    assert rebuilt.last_factual_qty("2312") == expected_last_2312
    assert rebuilt.quantity_basis("2311") == expected_basis_2311 == "factual"
    assert rebuilt.quantity_basis("2312") == expected_basis_2312 == "virtual"


def test_apply_inventory_rejects_negative_quantity() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    with pytest.raises(ValueError, match="negative"):
        stock.apply_inventory(
            as_of=datetime(2026, 10, 1, tzinfo=UTC),
            quantities={"2311": Decimal("-1")},
            inventory_id="inv-neg",
            partial=True,
        )
    assert stock.qty("2311") == Decimal("0")
    assert stock.pull_events() == ()


def test_rehydrate_matches_command_path_qty() -> None:
    machine = "701"
    stock = MicromarketDeviceStock(machine_code=machine)
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    events = stock.pull_events()
    rebuilt = MicromarketDeviceStock.rehydrate(machine_code=machine, events=events)
    assert rebuilt.qty("2311") == Decimal("10")
    assert rebuilt.has_completed_inventory is True


def test_sale_deduct_clamps_oversell_to_zero() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("2")},
        inventory_id="inv-1",
    )
    anomalies = stock.apply_sale_deduct(
        sale_source_id="sale-1",
        product_code="2311",
        qty=Decimal("5"),
        occurred_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("0")
    assert len(anomalies) == 1


def test_apply_loading_increases_qty() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("1")},
        inventory_id="inv-1",
    )
    stock.apply_loading(
        lines={"2311": Decimal("4")},
        loading_run_id="run-1",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("5")
    stock.apply_loading(
        lines={"2311": Decimal("4")},
        loading_run_id="run-1",
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("5")


def test_inventory_sets_has_completed_inventory() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    assert stock.has_completed_inventory is False
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("0")},
        inventory_id="inv-1",
    )
    assert stock.has_completed_inventory is True


def test_inventory_clears_seen_sale_source_ids_allowing_rededuct() -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-0",
    )
    stock.apply_sale_deduct(
        sale_source_id="s-after",
        product_code="2311",
        qty=Decimal("2"),
        occurred_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
    )
    assert stock.qty("2311") == Decimal("8")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    anomalies = stock.apply_sale_deduct(
        sale_source_id="s-after",
        product_code="2311",
        qty=Decimal("3"),
        occurred_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
    )
    assert anomalies == ()
    assert stock.qty("2311") == Decimal("7")
    assert stock.has_seen_sale_source_id("s-after") is True
