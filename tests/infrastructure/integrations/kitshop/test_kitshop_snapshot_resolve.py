from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    InMemoryKitShopReferenceSnapshotStore,
    KitShopReferenceSnapshot,
    KitShopSnapshotProduct,
    KitShopSnapshotShop,
)


def _client_with_store(
    store: InMemoryKitShopReferenceSnapshotStore,
) -> KitShopHttpClient:
    client = object.__new__(KitShopHttpClient)
    client.api = SimpleNamespace(account=SimpleNamespace(kit_company_id=42))
    client.settings = KitShopSettings()
    client.reference_snapshot_store = store
    return client


def test_shop_name_and_vendor_code_resolve_from_snapshot() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    store.replace(
        KitShopReferenceSnapshot(
            kit_company_id=42,
            refreshed_at=datetime.now(tz=UTC),
            groups=(),
            shops=(
                KitShopSnapshotShop(
                    shop_id=7,
                    shop_name="Офис [701]",
                    product_base_template_id=1,
                ),
            ),
            products=(
                KitShopSnapshotProduct(
                    product_id=100,
                    vendor_code="2311",
                    product_name="Вода",
                    is_deleted=False,
                ),
            ),
        )
    )
    client = _client_with_store(store)
    assert client.shop_name(7) == "Офис [701]"
    assert client.vendor_code(100) == "2311"
    assert client.shop_name(999) is None
    assert client.vendor_code(999) is None


def test_resolve_miss_when_store_empty() -> None:
    client = _client_with_store(InMemoryKitShopReferenceSnapshotStore())
    assert client.shop_name(1) is None
    assert client.vendor_code(1) is None
