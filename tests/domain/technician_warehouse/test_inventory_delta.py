from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.domain.technician_warehouse.helpers import (
    _T0,
    _T1,
    _T2,
    _T4,
    _TECHNICIAN_ID,
    _loading_event,
    _supply_event,
    _warehouse_with_baseline,
)

from src.domain.technician_warehouse import SYNTHETIC_ZERO_BASELINE_ID, TechnicianWarehouse
from src.domain.technician_warehouse.models import TransferDirection

_SYNTHETIC_MOMENT = datetime(1, 1, 1, tzinfo=UTC)


def test_first_form_inventory_opens_delta_vs_synthetic_zero() -> None:
    # happy: sole form inventory + loading → previous synthetic
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_loading(_loading_event("load-1", "3", submitted_at=_T1))
    event = warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_T2,
        actual_by_sku={"coffee": Decimal("0")},
        baseline=False,
    )
    assert event.baseline is False
    delta = warehouse.compute_warehouse_delta_between_latest_inventories()
    assert delta is not None
    assert delta.previous_inventory_id == SYNTHETIC_ZERO_BASELINE_ID
    assert delta.previous_inventory_moment == _SYNTHETIC_MOMENT
    assert delta.previous_actual_by_sku == {}
    assert delta.current_inventory_id == "inv-1"
    assert delta.loadings_by_sku.get("coffee") == Decimal("3")
    # calculated = 0 + 0 - 0 - 3 = -3; delta = actual0 - calculated = +3
    assert delta.delta_by_sku.get("coffee") == Decimal("3")


def test_seed_only_inventory_does_not_open_session_delta() -> None:
    # edge: baseline=True sole inventory
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="seed:tech-1:2026-05-01T00:00:00+00:00",
        form_token="seed:tech-1:2026-05-01T00:00:00+00:00",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=True,
    )
    assert warehouse.compute_warehouse_delta_between_latest_inventories() is None


def test_seed_then_form_uses_seed_as_previous() -> None:
    # happy: seed then form
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="seed:tech-1:t",
        form_token="seed:tech-1:t",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=True,
    )
    warehouse.clear_pending_events()
    warehouse.observe_transfer(
        _supply_event("in-1", "10", TransferDirection.SUPPLY_IN, updated_at=_T2),
    )
    warehouse.count_inventory(
        inventory_id="inv-form",
        form_token="form-token",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("25")},
        baseline=False,
    )
    delta = warehouse.compute_warehouse_delta_between_latest_inventories()
    assert delta is not None
    assert delta.previous_inventory_id == "seed:tech-1:t"
    assert delta.current_inventory_id == "inv-form"


def test_rehydrate_matches_synthetic_session_delta_command_path() -> None:
    # replay-parity
    command = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    command.observe_loading(_loading_event("load-1", "2", submitted_at=_T1))
    command.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_T2,
        actual_by_sku={},
        baseline=False,
    )
    events = list(command.collect_events())
    command.clear_pending_events()
    replayed = TechnicianWarehouse.rehydrate(_TECHNICIAN_ID, events)
    assert (
        replayed.compute_warehouse_delta_between_latest_inventories()
        == command.compute_warehouse_delta_between_latest_inventories()
    )


def test_second_inventory_computes_actual_minus_calculated() -> None:
    warehouse = _warehouse_with_baseline({"coffee": Decimal("20")})
    warehouse.observe_transfer(
        _supply_event("in-1", "10", TransferDirection.SUPPLY_IN, updated_at=_T2)
    )
    warehouse.observe_transfer(
        _supply_event("ret-1", "2", TransferDirection.SUPPLY_RETURN, updated_at=_T2)
    )
    warehouse.observe_loading(_loading_event("load-1", "5"))
    warehouse.count_inventory(
        inventory_id="inv-2",
        form_token="token-2",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("21")},
        baseline=False,
    )
    assert warehouse.latest_warehouse_delta() is None
    assert warehouse.compute_warehouse_delta_between_latest_inventories().delta_by_sku == {
        "coffee": Decimal("-2")
    }


def test_delta_excludes_transfers_and_loadings_outside_inventory_window() -> None:
    warehouse = _warehouse_with_baseline({"coffee": Decimal("20")})
    warehouse.observe_transfer(
        _supply_event("outside-transfer", "99", updated_at=_T0, observed_at=_T0)
    )
    warehouse.observe_transfer(
        _supply_event("inside-transfer", "10", updated_at=_T2, observed_at=_T2)
    )
    warehouse.observe_loading(_loading_event("outside-load", "50", submitted_at=_T0))
    warehouse.observe_loading(_loading_event("inside-load", "5", submitted_at=_T2))
    warehouse.count_inventory(
        inventory_id="inv-2",
        form_token="token-2",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("21")},
        baseline=False,
    )
    delta = warehouse.compute_warehouse_delta_between_latest_inventories()
    assert delta is not None
    assert delta.delta_by_sku == {"coffee": Decimal("-4")}
    assert delta.transfer_document_ids == ("inside-transfer",)


def test_delta_transfer_audit_ids_are_sorted() -> None:
    warehouse = _warehouse_with_baseline({"coffee": Decimal("20")})
    warehouse.observe_transfer(_supply_event("move-b", "3", updated_at=_T2))
    warehouse.observe_transfer(_supply_event("move-a", "2", updated_at=_T2))
    warehouse.count_inventory(
        inventory_id="inv-2",
        form_token="token-2",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=False,
    )
    delta = warehouse.compute_warehouse_delta_between_latest_inventories()
    assert delta is not None
    assert delta.transfer_document_ids == ("move-a", "move-b")


def test_inventory_count_is_idempotent_by_form_token() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    first = warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="same",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    second = warehouse.count_inventory(
        inventory_id="inv-2",
        form_token="same",
        counted_at=_T2,
        actual_by_sku={"coffee": Decimal("11")},
        baseline=False,
    )
    assert first == second
    assert len(warehouse.collect_events()) == 1


def test_rehydrate_restores_latest_warehouse_delta() -> None:
    command = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    command.count_inventory(
        inventory_id="inv-baseline",
        form_token="baseline-token",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=False,
    )
    command.observe_transfer(_supply_event("in-1", "10", updated_at=_T2))
    command.observe_transfer(
        _supply_event("ret-1", "2", TransferDirection.SUPPLY_RETURN, updated_at=_T2)
    )
    command.observe_loading(_loading_event("load-1", "5"))
    command.count_inventory(
        inventory_id="inv-2",
        form_token="token-2",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("21")},
        baseline=False,
    )
    events = list(command.collect_events())

    replayed = TechnicianWarehouse.rehydrate(_TECHNICIAN_ID, events)
    assert replayed.latest_warehouse_delta() is None
    assert command.latest_warehouse_delta() is None
    computed = replayed.compute_warehouse_delta_between_latest_inventories()
    assert computed is not None
    assert computed.delta_by_sku == {"coffee": Decimal("-2")}
    assert computed == command.compute_warehouse_delta_between_latest_inventories()


def test_rehydrate_matches_command_path_without_pending_events() -> None:
    command = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    command.count_inventory(
        inventory_id="inv-baseline",
        form_token="baseline-token",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=False,
    )
    command.observe_transfer(_supply_event("in-1", "10", updated_at=_T2))
    command.observe_loading(_loading_event("load-1", "5"))
    command.count_inventory(
        inventory_id="inv-2",
        form_token="token-2",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("21")},
        baseline=False,
    )
    events = list(command.collect_events())
    command.clear_pending_events()

    replayed = TechnicianWarehouse.rehydrate(_TECHNICIAN_ID, events)
    assert replayed.collect_events() == ()
    assert replayed.calculated_stock_since_baseline() == command.calculated_stock_since_baseline()
    assert replayed.latest_warehouse_delta() is None
    assert command.latest_warehouse_delta() is None
    assert (
        replayed.compute_warehouse_delta_between_latest_inventories()
        == command.compute_warehouse_delta_between_latest_inventories()
    )
