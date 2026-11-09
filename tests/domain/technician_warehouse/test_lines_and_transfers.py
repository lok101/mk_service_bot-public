from __future__ import annotations

from decimal import Decimal

import pytest
from tests.domain.technician_warehouse.helpers import (
    _T1,
    _T2,
    _T3,
    _TECHNICIAN_ID,
    _loading_event,
    _supply_event,
)

from src.domain.technician_warehouse import (
    FinalizedTransferChangedError,
    TechnicianWarehouse,
    TechnicianWarehouseLine,
    TransferDirection,
)


def test_warehouse_line_requires_positive_base_quantity() -> None:
    with pytest.raises(ValueError, match="positive"):
        TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("0"))


def test_warehouse_line_rejects_empty_sku() -> None:
    with pytest.raises(ValueError, match="SKU"):
        TechnicianWarehouseLine(sku="   ", quantity_base=Decimal("1"))


def test_transfer_direction_has_stable_values() -> None:
    assert TransferDirection.SUPPLY_IN.value == "supply_in"
    assert TransferDirection.SUPPLY_RETURN.value == "supply_return"


def test_supply_in_and_return_change_calculated_stock() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(_supply_event("in-1", "10", TransferDirection.SUPPLY_IN))
    warehouse.observe_transfer(_supply_event("ret-1", "3", TransferDirection.SUPPLY_RETURN))
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("7")


def test_latest_transfer_version_wins_and_void_removes_document() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(_supply_event("move-1", "10", updated_at=_T1))
    warehouse.observe_transfer(_supply_event("move-1", "12", updated_at=_T2))
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("12")
    warehouse.void_transfer(external_document_id="move-1", observed_at=_T3)
    assert warehouse.calculated_stock_since_baseline() == {}


def test_transfer_correction_with_same_version_key_applies_new_hash() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(
        _supply_event("move-1", "10", updated_at=_T1, content_hash="hash-v1")
    )
    result = warehouse.observe_transfer(
        _supply_event("move-1", "12", updated_at=_T1, content_hash="hash-v2")
    )
    assert result is not None
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("12")


def test_loading_is_idempotent_by_source_event_id() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    first = warehouse.observe_loading(_loading_event("event-1", "4"))
    second = warehouse.observe_loading(_loading_event("event-1", "4"))
    assert first is not None
    assert second is None
    assert len(warehouse.collect_events()) == 1


def test_changed_or_voided_finalized_transfer_is_rejected() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(_supply_event("move-1", "10", updated_at=_T1))
    warehouse.finalize_transfers(
        session_id="session-1",
        external_document_ids=("move-1",),
        finalized_at=_T2,
    )
    with pytest.raises(FinalizedTransferChangedError, match="move-1"):
        warehouse.observe_transfer(_supply_event("move-1", "12", updated_at=_T3))
    with pytest.raises(FinalizedTransferChangedError, match="move-1"):
        warehouse.void_transfer(external_document_id="move-1", observed_at=_T3)


def test_finalized_transfer_exact_replay_is_noop() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    event = _supply_event("move-1", "10", updated_at=_T1)
    warehouse.observe_transfer(event)
    warehouse.finalize_transfers(
        session_id="session-1",
        external_document_ids=("move-1",),
        finalized_at=_T2,
    )
    pending_before = len(warehouse.collect_events())
    replay = warehouse.observe_transfer(event)
    assert replay is None
    assert len(warehouse.collect_events()) == pending_before
    assert warehouse.calculated_stock_since_baseline()["coffee"] == Decimal("10")


def test_void_transfer_is_idempotent_for_same_document() -> None:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.observe_transfer(_supply_event("move-1", "10", updated_at=_T1))
    first = warehouse.void_transfer(external_document_id="move-1", observed_at=_T2)
    second = warehouse.void_transfer(external_document_id="move-1", observed_at=_T3)
    assert first is not None
    assert second is None
    assert len(warehouse.collect_events()) == 2
    assert warehouse.calculated_stock_since_baseline() == {}
