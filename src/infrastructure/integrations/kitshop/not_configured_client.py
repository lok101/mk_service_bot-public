from __future__ import annotations

import logging
from datetime import datetime
from typing import NoReturn

from beartype import beartype

from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.sale import KitShopSale
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop

_LOGGER = logging.getLogger(__name__)
_WARNED = False


@beartype
class NotConfiguredKitShopClient:
    """Stub without HTTP when kit_shop credentials are missing.

    См. docs/specs/2026-09-04-kitshop-adapter-design.md.
    """

    def _raise_not_configured(self) -> NoReturn:
        global _WARNED  # noqa: PLW0603
        if not _WARNED:
            _LOGGER.warning("kitshop_client_not_configured")
            _WARNED = True
        raise RuntimeError("Kit Shop client is not configured")

    @beartype
    def get_sales(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> list[KitShopSale]:
        del from_date, to_date
        self._raise_not_configured()

    @beartype
    def get_sale_by_id(self, *, sale_id: int) -> KitShopSale:
        del sale_id
        self._raise_not_configured()

    @beartype
    def get_shops(self) -> list[KitShopShop]:
        self._raise_not_configured()

    @beartype
    def get_products(self) -> list[KitShopProduct]:
        self._raise_not_configured()

    @beartype
    def shop_name(self, shop_id: int) -> str | None:
        del shop_id
        self._raise_not_configured()

    @beartype
    def vendor_code(self, product_id: int) -> str | None:
        del product_id
        self._raise_not_configured()
