from __future__ import annotations

from datetime import UTC, datetime

from src.config.mongodb import MongoSettings
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    InMemoryKitShopReferenceSnapshotStore,
    KitShopReferenceSnapshot,
    KitShopSnapshotGroup,
    KitShopSnapshotProduct,
    KitShopSnapshotShop,
)
from src.infrastructure.mongodb.kitshop_reference_snapshots import (
    MongoKitShopReferenceSnapshotStore,
)


def _sample_snapshot(*, company_id: int = 10) -> KitShopReferenceSnapshot:
    return KitShopReferenceSnapshot(
        kit_company_id=company_id,
        refreshed_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        groups=(KitShopSnapshotGroup(group_id=1, group_name="Полка A"),),
        shops=(
            KitShopSnapshotShop(
                shop_id=5,
                shop_name="Холодильник [101]",
                product_base_template_id=7,
            ),
        ),
        products=(
            KitShopSnapshotProduct(
                product_id=9,
                vendor_code="d-1001",
                product_name="Вода",
                is_deleted=False,
            ),
        ),
    )


def test_memory_store_replace_and_get_roundtrip() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    snapshot = _sample_snapshot()
    store.replace(snapshot)
    loaded = store.get(10)
    assert loaded == snapshot


def test_store_get_returns_none_when_missing() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    assert store.get(10) is None


def test_mongo_store_replace_and_get_roundtrip() -> None:
    import mongomock

    client = mongomock.MongoClient()
    collection = client["db"]["kitshop_reference_snapshots"]
    store = MongoKitShopReferenceSnapshotStore(collection)
    snapshot = _sample_snapshot()
    store.replace(snapshot)
    loaded = store.get(10)
    assert loaded == snapshot
    # second replace overwrites atomically
    updated = KitShopReferenceSnapshot(
        kit_company_id=10,
        refreshed_at=datetime(2026, 10, 13, 13, 0, tzinfo=UTC),
        groups=(),
        shops=(),
        products=(),
    )
    store.replace(updated)
    assert store.get(10) == updated


def test_mongo_settings_kitshop_reference_snapshots_default() -> None:
    assert MongoSettings().kitshop_reference_snapshots_collection == "kitshop_reference_snapshots"
