from __future__ import annotations

from decimal import Decimal

import pytest
from tests.domain.technician_warehouse.helpers import (
    _SYNTHETIC_MOMENT,
    _T0,
    _T1,
    _T2,
    _T3,
    _T4,
    _TECHNICIAN_ID,
    _closed_warehouse,
    _loading_event,
    _supply_event,
    _warehouse_with_baseline,
)

from src.domain.ids import EventId
from src.domain.technician_warehouse import (
    SYNTHETIC_ZERO_BASELINE_ID,
    TechnicianWarehouse,
    TechnicianWarehouseExitClosed,
    TransferDirection,
    WarehouseAlreadyClosed,
)


def test_exit_closed_event_exposes_schema_fields() -> None:
    event = TechnicianWarehouseExitClosed(
        event_id=EventId("exit-1"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_T4,
        closed_at=_T4,
        return_external_document_id="move-return-1",
        return_content_hash="hash-return-1",
    )
    assert event.event_id.value == "exit-1"
    assert event.return_external_document_id == "move-return-1"
    assert event.return_content_hash == "hash-return-1"
    assert event.closed_at == _T4


def test_close_exit_sets_is_closed_and_delta_actual_empty() -> None:
    warehouse = _warehouse_with_baseline({"coffee": Decimal("10")})
    ret = _supply_event("move-ret", "10", TransferDirection.SUPPLY_RETURN, updated_at=_T2)
    warehouse.observe_transfer(ret)
    warehouse.clear_pending_events()
    event = warehouse.close_exit(
        closed_at=_T4,
        return_external_document_id="move-ret",
        return_content_hash=ret.content_hash,
    )
    assert warehouse.is_closed() is True
    assert warehouse.exit_closed_at() == _T4
    assert event.event_id.value
    delta = warehouse.latest_warehouse_delta()
    assert delta is not None
    assert delta.actual_by_sku == {}
    assert delta.current_inventory_id == event.event_id.value
    assert delta.current_inventory_moment == _T4
    assert delta.previous_inventory_id == "inv-baseline"
    assert delta.returns_by_sku.get("coffee") == Decimal("10")


def test_rehydrate_matches_close_exit_command_path() -> None:
    ret = _supply_event("move-ret", "10", TransferDirection.SUPPLY_RETURN, updated_at=_T2)
    command = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    baseline = command.count_inventory(
        inventory_id="inv-baseline",
        form_token="token-baseline",
        counted_at=_T0,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    observed = command.observe_transfer(ret)
    assert observed is not None
    exit_event = command.close_exit(
        closed_at=_T4,
        return_external_document_id="move-ret",
        return_content_hash=ret.content_hash,
    )
    rehydrated = TechnicianWarehouse.rehydrate(
        _TECHNICIAN_ID,
        [baseline, observed, exit_event],
    )
    assert rehydrated.is_closed() is True
    assert rehydrated.exit_closed_at() == _T4
    assert rehydrated.latest_warehouse_delta() == command.latest_warehouse_delta()
    assert rehydrated.collect_events() == ()


def test_post_exit_observe_and_inventory_raise_warehouse_already_closed() -> None:
    warehouse = _closed_warehouse()
    with pytest.raises(WarehouseAlreadyClosed, match="tech-1"):
        warehouse.count_inventory(
            inventory_id="inv-2",
            form_token="token-2",
            counted_at=_T4,
            actual_by_sku={},
            baseline=False,
        )
    with pytest.raises(WarehouseAlreadyClosed, match="tech-1"):
        warehouse.observe_loading(_loading_event("load-1", "1"))
    with pytest.raises(WarehouseAlreadyClosed, match="tech-1"):
        warehouse.observe_transfer(
            _supply_event("move-late", "1", TransferDirection.SUPPLY_IN, updated_at=_T4),
        )
    with pytest.raises(WarehouseAlreadyClosed, match="tech-1"):
        warehouse.void_transfer(external_document_id="move-ret", observed_at=_T4)


def test_finalize_transfers_allowed_after_exit_close() -> None:
    warehouse = _closed_warehouse()
    event = warehouse.finalize_transfers(
        session_id="tech-1:2026-07-01T13:00:00+00:00",
        external_document_ids=("move-ret",),
        finalized_at=_T4,
    )
    assert event.session_id.startswith("tech-1:")
    assert warehouse.is_transfer_finalized("move-ret") is True


def test_second_close_exit_raises_warehouse_already_closed() -> None:
    warehouse = _closed_warehouse()
    with pytest.raises(WarehouseAlreadyClosed, match="tech-1"):
        warehouse.close_exit(
            closed_at=_T4,
            return_external_document_id="move-ret",
            return_content_hash="x",
        )


def test_close_exit_without_inventory_uses_synthetic_zero_baseline() -> None:
    # happy: no inventory; supply_in + loading + return → book then actual={}
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(
        _supply_event("in-1", "10", TransferDirection.SUPPLY_IN, updated_at=_T1),
    )
    warehouse.observe_loading(_loading_event("load-1", "3", submitted_at=_T2))
    ret = _supply_event(
        "ret-1",
        "5",
        TransferDirection.SUPPLY_RETURN,
        updated_at=_T3,
    )
    warehouse.observe_transfer(ret)
    warehouse.clear_pending_events()
    event = warehouse.close_exit(
        closed_at=_T4,
        return_external_document_id="ret-1",
        return_content_hash=ret.content_hash,
    )
    assert warehouse.is_closed() is True
    delta = warehouse.latest_warehouse_delta()
    assert delta is not None
    assert delta.previous_inventory_id == SYNTHETIC_ZERO_BASELINE_ID
    assert delta.previous_inventory_moment == _SYNTHETIC_MOMENT
    assert delta.previous_actual_by_sku == {}
    assert delta.actual_by_sku == {}
    assert delta.current_inventory_id == event.event_id.value
    # book = 10 - 5 - 3 = 2 → delta = 0 - 2 = -2
    assert delta.delta_by_sku.get("coffee") == Decimal("-2")
    assert delta.supply_in_by_sku.get("coffee") == Decimal("10")
    assert delta.returns_by_sku.get("coffee") == Decimal("5")
    assert delta.loadings_by_sku.get("coffee") == Decimal("3")


def test_rehydrate_matches_synthetic_close_exit_command_path() -> None:
    # replay-parity
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    supply = warehouse.observe_transfer(
        _supply_event("in-1", "4", TransferDirection.SUPPLY_IN, updated_at=_T1),
    )
    assert supply is not None
    ret_event = _supply_event(
        "ret-1",
        "4",
        TransferDirection.SUPPLY_RETURN,
        updated_at=_T2,
    )
    returned = warehouse.observe_transfer(ret_event)
    assert returned is not None
    exit_event = warehouse.close_exit(
        closed_at=_T4,
        return_external_document_id="ret-1",
        return_content_hash=ret_event.content_hash,
    )
    command_delta = warehouse.latest_warehouse_delta()
    rehydrated = TechnicianWarehouse.rehydrate(
        _TECHNICIAN_ID,
        [supply, returned, exit_event],
    )
    assert rehydrated.is_closed() is True
    assert rehydrated.latest_warehouse_delta() == command_delta
    assert rehydrated.collect_events() == ()
