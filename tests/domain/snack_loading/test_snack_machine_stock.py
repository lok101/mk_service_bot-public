from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.ids import EventId
from src.domain.snack_loading import SnackMachineStock


def test_rehydrate_matches_command_path_qty() -> None:
    machine = "514"
    key = ("514", "SnackA", 1)
    stock = SnackMachineStock(machine_code=machine)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        quantities={key: Decimal("10")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    events = stock.pull_events()
    rebuilt = SnackMachineStock.rehydrate(machine_code=machine, events=events)
    assert rebuilt.qty(*key) == Decimal("10")
    assert rebuilt.has_completed_inventory is True


def test_sale_deduct_reduces_qty() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("5")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    stock.apply_sale_deduct(
        source_id="s1",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert stock.qty(*key) == Decimal("3")


def test_sale_deduct_clamps_oversell_to_zero() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("1")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    anomalies = stock.apply_sale_deduct(
        source_id="s2",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("5"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert stock.qty(*key) == Decimal("0")
    assert anomalies  # non-empty anomaly markers / events


def test_apply_sale_idempotent_by_source_id() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("5")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    kwargs = dict(
        source_id="s1",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    stock.apply_sale_deduct(**kwargs)
    stock.apply_sale_deduct(**kwargs)
    assert stock.qty(*key) == Decimal("3")


def test_inventory_sets_has_completed_inventory() -> None:
    stock = SnackMachineStock(machine_code="514")
    assert stock.has_completed_inventory is False
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("1")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    assert stock.has_completed_inventory is True


def test_loading_applied_increases_qty() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("1")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    stock.apply_loading(
        run_id="run-1",
        move_id="move-1",
        increments={key: Decimal("4")},
        occurred_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert stock.qty(*key) == Decimal("5")


def test_apply_inventory_rejects_foreign_machine_key() -> None:
    stock = SnackMachineStock(machine_code="514")
    with pytest.raises(ValueError, match="machine_code"):
        stock.apply_inventory(
            as_of=datetime(2026, 7, 1, tzinfo=UTC),
            quantities={("999", "SnackA", 1): Decimal("1")},
            product_by_key={("999", "SnackA", 1): "SKU1"},
            inventory_id="inv-1",
        )


def test_apply_loading_rejects_foreign_machine_key() -> None:
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("1")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    with pytest.raises(ValueError, match="machine_code"):
        stock.apply_loading(
            run_id="run-1",
            move_id="move-1",
            increments={("999", "SnackA", 1): Decimal("1")},
            occurred_at=datetime(2026, 7, 3, tzinfo=UTC),
        )


def test_inventory_event_has_event_id() -> None:
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("1")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="inv-1",
    )
    events = stock.pull_events()
    assert len(events) == 1
    assert isinstance(events[0].event_id, EventId)
    assert events[0].event_id.value.startswith("event-")


def test_sale_deduct_non_positive_quantity_is_noop() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("5")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    anomalies = stock.apply_sale_deduct(
        source_id="bad",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("-1"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert anomalies == ()
    assert stock.qty(*key) == Decimal("5")
    assert stock.pull_events() == ()
    # same source_id may still be applied later with a valid qty
    stock.apply_sale_deduct(
        source_id="bad",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert stock.qty(*key) == Decimal("4")


def test_inventory_clears_seen_source_ids_allowing_redeuct() -> None:
    stock = SnackMachineStock(machine_code="514")
    key = ("514", "SnackA", 1)
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={key: Decimal("5")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-0",
    )
    stock.pull_events()
    stock.apply_sale_deduct(
        source_id="s-after",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    stock.pull_events()
    # absolute recount (as_of path): reset qty, then replay same source_id
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        quantities={key: Decimal("10")},
        product_by_key={key: "SKU1"},
        inventory_id="inv-1",
    )
    stock.pull_events()
    stock.apply_sale_deduct(
        source_id="s-after",
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    assert stock.qty(*key) == Decimal("8")
