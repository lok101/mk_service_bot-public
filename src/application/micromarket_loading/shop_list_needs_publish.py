from __future__ import annotations

from beartype import beartype

from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.micromarket_loading.shop_list_publish_journal import ShopListPublishEffects


@beartype
def shop_list_effects_nonempty(effects: ShopListPublishEffects) -> bool:
    return bool(
        effects.disabled_product_codes
        or effects.enabled_product_codes
        or effects.added_product_codes
        or effects.removed_product_codes
        or effects.updated_product_codes
    )


@beartype
def shop_list_needs_publish(
    *,
    status: ShopListPublishStatus,
    effects: ShopListPublishEffects,
) -> bool:
    """Whether catch-up enqueue is warranted for loading-shelf / similar hooks.

    ``PUBLISHING`` is included so a concurrent publish can still request catch-up
    via the existing enqueue path.
    """
    if status is not ShopListPublishStatus.PUBLISHED:
        return True
    return shop_list_effects_nonempty(effects)
