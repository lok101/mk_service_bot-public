from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import EventId, TechnicianId
from src.domain.technician_warehouse import (
    TechnicianWarehouse,
    TechnicianWarehouseLine,
    TechnicianWarehouseTransferObserved,
    TransferDirection,
)


def _tid() -> TechnicianId:
    return TechnicianId("10001")


def test_inventory_apply_does_not_set_latest_delta() -> None:
    wh = TechnicianWarehouse.empty(_tid())
    wh.count_inventory(
        inventory_id="inv-1",
        form_token="tok-1",
        counted_at=datetime(2026, 6, 1, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    wh.count_inventory(
        inventory_id="inv-2",
        form_token="tok-2",
        counted_at=datetime(2026, 6, 10, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("8")},
        baseline=False,
    )
    assert wh.latest_warehouse_delta() is None


def test_compute_delta_includes_transfer_observed_after_inventory_event_order() -> None:
    wh = TechnicianWarehouse.empty(_tid())
    wh.count_inventory(
        inventory_id="inv-1",
        form_token="tok-1",
        counted_at=datetime(2026, 6, 1, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    wh.count_inventory(
        inventory_id="inv-2",
        form_token="tok-2",
        counted_at=datetime(2026, 6, 10, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("8")},
        baseline=False,
    )
    # late transfer in window (as if sync after form)
    transfer = TechnicianWarehouseTransferObserved(
        event_id=EventId("e-tr"),
        technician_id=_tid(),
        occurred_at=datetime(2026, 6, 11, tzinfo=UTC),
        external_document_id="ms-1",
        content_hash="h1",
        direction=TransferDirection.SUPPLY_IN,
        moment=datetime(2026, 6, 5, tzinfo=UTC),
        updated_at=datetime(2026, 6, 5, tzinfo=UTC),
        observed_at=datetime(2026, 6, 11, tzinfo=UTC),
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("2")),),
    )
    observed = wh.observe_transfer(transfer)
    assert observed is not None
    delta = wh.compute_warehouse_delta_between_latest_inventories()
    assert delta is not None
    assert delta.supply_in_by_sku.get("coffee") == Decimal("2")


def test_rehydrate_matches_inventory_without_latest_delta() -> None:
    wh = TechnicianWarehouse.empty(_tid())
    wh.count_inventory(
        inventory_id="inv-1",
        form_token="tok-1",
        counted_at=datetime(2026, 6, 1, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    wh.count_inventory(
        inventory_id="inv-2",
        form_token="tok-2",
        counted_at=datetime(2026, 6, 10, tzinfo=UTC),
        actual_by_sku={"coffee": Decimal("8")},
        baseline=False,
    )
    command_delta = wh.compute_warehouse_delta_between_latest_inventories()
    events = wh.collect_events()
    restored = TechnicianWarehouse.rehydrate(_tid(), events)
    assert restored.latest_warehouse_delta() is None
    assert wh.latest_warehouse_delta() is None
    assert restored.compute_warehouse_delta_between_latest_inventories() == command_delta
    assert command_delta is not None
