from __future__ import annotations

from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.micromarket_loading.shop_list_needs_publish import shop_list_needs_publish
from src.application.micromarket_loading.shop_list_publish_journal import ShopListPublishEffects


def test_needs_publish_when_unpublished() -> None:
    assert shop_list_needs_publish(
        status=ShopListPublishStatus.UNPUBLISHED,
        effects=ShopListPublishEffects(),
    )


def test_needs_publish_when_published_with_added() -> None:
    assert shop_list_needs_publish(
        status=ShopListPublishStatus.PUBLISHED,
        effects=ShopListPublishEffects(added_product_codes=("n-1",)),
    )


def test_skips_when_published_and_empty_diff() -> None:
    assert not shop_list_needs_publish(
        status=ShopListPublishStatus.PUBLISHED,
        effects=ShopListPublishEffects(),
    )
