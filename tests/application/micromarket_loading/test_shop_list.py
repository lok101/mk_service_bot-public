from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    SaveMicromarketPlanogram,
)
from src.application.micromarket_loading.shop_list import (
    ShopListPublishStatus,
    UnavailableMicromarketShopListPublisher,
)
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryMicromarketPlanogramStore


def test_planogram_save_does_not_accept_publisher() -> None:
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(TypeError):
        SaveMicromarketPlanogram(
            store=store,
            catalog_codes={"2311"},
            shop_list=UnavailableMicromarketShopListPublisher(),
        )


def test_planogram_save_does_not_publish() -> None:
    store = InMemoryMicromarketPlanogramStore()
    saved = SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        machine_code="701",
        shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
        lines=(
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=4,
                price_rub=Decimal("10"),
                active=True,
                sort_order=1,
                kit_group_id=6348,
            ),
            MicromarketPlanogramLine(
                product_code="2312",
                target_qty=2,
                price_rub=Decimal("20"),
                active=False,
                sort_order=2,
                kit_group_id=6348,
            ),
        ),
    )
    assert saved.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert store.get("701") is not None


def test_publish_without_adapter_stays_unpublished() -> None:
    publisher = UnavailableMicromarketShopListPublisher()
    status = publisher.status(machine_code="701")
    assert status is ShopListPublishStatus.UNPUBLISHED
    assert status.label_ru == "не опубликован"
