from __future__ import annotations

from decimal import Decimal

from tests.domain.technician_warehouse.helpers import (
    _T1,
    _T2,
    _T3,
    _T4,
    _TECHNICIAN_ID,
    _loading_event,
)

from src.domain.technician_warehouse import TechnicianWarehouse


def test_compute_delta_for_inventory_id_uses_named_current_not_latest() -> None:
    # happy: stream inv-old → inv-mid → inv-new; delta for mid ignores latest
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-old",
        form_token="token-old",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    warehouse.observe_loading(_loading_event("load-mid", "3", submitted_at=_T2))
    warehouse.count_inventory(
        inventory_id="inv-mid",
        form_token="token-mid",
        counted_at=_T3,
        actual_by_sku={"coffee": Decimal("7")},
        baseline=False,
    )
    warehouse.count_inventory(
        inventory_id="inv-new",
        form_token="token-new",
        counted_at=_T4,
        actual_by_sku={"coffee": Decimal("5")},
        baseline=False,
    )

    delta = warehouse.compute_warehouse_delta_for_inventory_id("inv-mid")
    assert delta is not None
    assert delta.current_inventory_id == "inv-mid"
    assert delta.previous_inventory_id == "inv-old"
    assert delta.loadings_by_sku.get("coffee") == Decimal("3")

    latest = warehouse.compute_warehouse_delta_between_latest_inventories()
    assert latest is not None
    assert latest.current_inventory_id == "inv-new"


def test_compute_delta_for_unknown_inventory_id_returns_none_or_raises() -> None:
    # error: unknown id → None (planner maps to ReconciliationBlocked)
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token="token-1",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    assert warehouse.compute_warehouse_delta_for_inventory_id("missing") is None


def test_compute_delta_for_baseline_inventory_returns_none() -> None:
    # edge: seed baseline does not open session
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="seed:tech-1:t",
        form_token="seed:tech-1:t",
        counted_at=_T1,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=True,
    )
    assert warehouse.compute_warehouse_delta_for_inventory_id("seed:tech-1:t") is None
