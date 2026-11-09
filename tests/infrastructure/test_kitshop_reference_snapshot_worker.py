from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.api_models.matrix import KitShopProductGroup
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    InMemoryKitShopReferenceSnapshotStore,
)
from src.infrastructure.kitshop_reference_snapshot_worker import (
    KitShopReferenceSnapshotWorker,
)


@dataclass
class _FakeAccount:
    kit_company_id: int = 42


@dataclass
class _FakeApi:
    account: _FakeAccount = field(default_factory=_FakeAccount)
    groups: list[KitShopProductGroup] = field(default_factory=list)
    shops: list[KitShopShop] = field(default_factory=list)
    products: list[KitShopProduct] = field(default_factory=list)
    fail_on: str | None = None
    calls: list[str] = field(default_factory=list)

    def get_product_groups(self) -> list[KitShopProductGroup]:
        self.calls.append("groups")
        if self.fail_on == "groups":
            raise RuntimeError("groups failed")
        return list(self.groups)

    def get_shops(self) -> list[KitShopShop]:
        self.calls.append("shops")
        if self.fail_on == "shops":
            raise RuntimeError("shops failed")
        return list(self.shops)

    def get_products(self) -> list[KitShopProduct]:
        self.calls.append("products")
        if self.fail_on == "products":
            raise RuntimeError("products failed")
        return list(self.products)


def _sample_api(**kwargs: object) -> _FakeApi:
    return _FakeApi(
        groups=[KitShopProductGroup.model_validate({"GroupId": 1, "GroupName": "A"})],
        shops=[
            KitShopShop.model_validate(
                {
                    "ShopId": 10,
                    "ShopName": "S",
                    "CompanyId": 42,
                    "ProductBaseTemplateId": 7,
                }
            )
        ],
        products=[
            KitShopProduct.model_validate(
                {
                    "ProductId": 100,
                    "ProductName": "P",
                    "VendorCode": "VC",
                    "IsDeleted": False,
                }
            )
        ],
        **kwargs,  # type: ignore[arg-type]
    )


def test_refresh_once_writes_full_snapshot() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    api = _sample_api()
    worker = KitShopReferenceSnapshotWorker(
        store=store,
        api=api,
        refresh_interval_seconds=3600.0,
    )

    worker.refresh_once()

    snap = store.get(42)
    assert snap is not None
    assert snap.kit_company_id == 42
    assert snap.refreshed_at.tzinfo is not None
    assert snap.groups[0].group_name == "A"
    assert snap.shops[0].shop_id == 10
    assert snap.products[0].vendor_code == "VC"
    assert api.calls == ["groups", "shops", "products"]


def test_refresh_once_keeps_previous_on_mid_failure() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    good = _sample_api()
    worker = KitShopReferenceSnapshotWorker(
        store=store,
        api=good,
        refresh_interval_seconds=3600.0,
    )
    worker.refresh_once()
    previous = store.get(42)
    assert previous is not None

    failing = _sample_api(fail_on="shops")
    worker = KitShopReferenceSnapshotWorker(
        store=store,
        api=failing,
        refresh_interval_seconds=3600.0,
    )
    with pytest.raises(RuntimeError, match="shops failed"):
        worker.refresh_once()

    assert store.get(42) is previous


def test_run_immediate_then_interval_until_stop() -> None:
    store = InMemoryKitShopReferenceSnapshotStore()
    api = _sample_api()
    worker = KitShopReferenceSnapshotWorker(
        store=store,
        api=api,
        refresh_interval_seconds=0.05,
    )

    async def _run() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop))
        for _ in range(50):
            if store.get(42) is not None:
                break
            await asyncio.sleep(0.02)
        assert store.get(42) is not None
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)

    asyncio.run(_run())


def test_kitshop_reference_refresh_interval_default() -> None:
    assert KitShopSettings().reference_refresh_interval_seconds == 3600
