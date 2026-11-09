from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from beartype import beartype

from src.config.kitshop import KitShopSettings
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.sale import KitShopSale
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.http_client import KitShopApiClient
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshot,
    KitShopReferenceSnapshotStore,
)
from src.infrastructure.rate_limiting import KitShopApiPriority

_LOGGER: Final = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class KitShopHttpClient:
    """Sync HTTP facade: sales list/detail + local snapshot resolve for shop/product.

    См. docs/specs/2026-09-04-kitshop-adapter-design.md · ADR-0051.
    """

    api: KitShopApiClient
    settings: KitShopSettings
    reference_snapshot_store: KitShopReferenceSnapshotStore | None = None

    @beartype
    def get_sales(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
        priority: KitShopApiPriority | None = None,
    ) -> list[KitShopSale]:
        return self.api.get_sales(
            from_date=from_date,
            to_date=to_date,
            priority=priority,
        )

    @beartype
    def get_sale_by_id(
        self,
        *,
        sale_id: int,
        priority: KitShopApiPriority | None = None,
    ) -> KitShopSale:
        return self.api.get_sale_by_id(sale_id=sale_id, priority=priority)

    @beartype
    def get_shops(self) -> list[KitShopShop]:
        shops = self.api.get_shops()
        _LOGGER.info("kitshop_shops_fetched", extra={"count": len(shops)})
        return shops

    @beartype
    def get_products(self) -> list[KitShopProduct]:
        products = self.api.get_products()
        _LOGGER.info("kitshop_products_fetched", extra={"count": len(products)})
        return products

    @beartype
    def shop_name(self, shop_id: int) -> str | None:
        snapshot = self._snapshot()
        if snapshot is None:
            return None
        for shop in snapshot.shops:
            if shop.shop_id == shop_id:
                return shop.shop_name
        return None

    @beartype
    def vendor_code(self, product_id: int) -> str | None:
        snapshot = self._snapshot()
        if snapshot is None:
            return None
        for product in snapshot.products:
            if product.product_id == product_id:
                return product.vendor_code
        return None

    def _snapshot(self) -> KitShopReferenceSnapshot | None:
        if self.reference_snapshot_store is None:
            return None
        return self.reference_snapshot_store.get(int(self.api.account.kit_company_id))

    @beartype
    def close(self) -> None:
        self.api.close()
