from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)


def _mirror(
    *,
    catalog_code: str = "2311",
    supplier_id: str | None = "agent-1",
    supplier_name: str | None = "ООО Поставщик",
    last_buy_price: Decimal | None = Decimal("12.50"),
    supply_moment: datetime | None = None,
    synced_at: datetime | None = None,
) -> ProcurementMirror:
    return ProcurementMirror(
        catalog_code=catalog_code,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        last_buy_price=last_buy_price,
        supply_moment=supply_moment or datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        synced_at=synced_at or datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )


def test_memory_procurement_mirror_upsert_get_roundtrip() -> None:
    store = MemoryProcurementMirrorStore()
    row = _mirror()
    store.upsert(row)
    assert store.get("2311") == row


def test_memory_procurement_mirror_upsert_replaces_same_code() -> None:
    store = MemoryProcurementMirrorStore()
    store.upsert(_mirror(last_buy_price=Decimal("10.00")))
    updated = _mirror(last_buy_price=Decimal("15.00"), supplier_name="Другой")
    store.upsert(updated)
    assert store.get("2311") == updated


def test_memory_procurement_mirror_delete_removes_row() -> None:
    store = MemoryProcurementMirrorStore()
    store.upsert(_mirror())
    store.delete("2311")
    assert store.get("2311") is None


def test_memory_procurement_mirror_get_missing_returns_none() -> None:
    store = MemoryProcurementMirrorStore()
    assert store.get("missing") is None


def test_memory_procurement_mirror_delete_missing_is_noop() -> None:
    store = MemoryProcurementMirrorStore()
    store.delete("missing")
    assert store.get("missing") is None
