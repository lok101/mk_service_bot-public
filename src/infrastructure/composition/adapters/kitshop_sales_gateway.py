from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.infrastructure.integrations.kitshop.api_models.sale import KitShopSalePosition
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.parsing.datetime_kit import parse_kit_datetime


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSaleListItemView:
    sale_id: int
    sale_datetime: datetime


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSaleDetailView:
    sale_id: int
    company_id: int
    shop_id: int
    device_id: int
    sale_datetime: datetime
    positions: tuple[KitShopSalePosition, ...]


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSalesGatewayAdapter:
    """KitShopHttpClient → KitShopSalesGateway (datetime parsed to aware)."""

    client: KitShopHttpClient

    @beartype
    def list_sales_since(self, *, since: datetime, until: datetime) -> list[object]:
        sales = self.client.get_sales(from_date=since, to_date=until)
        items: list[object] = []
        for sale in sales:
            items.append(
                KitShopSaleListItemView(
                    sale_id=sale.sale_id,
                    sale_datetime=parse_kit_datetime(sale.sale_datetime),
                ),
            )
        return items

    @beartype
    def get_sale_detail(self, sale_id: int) -> object:
        sale = self.client.get_sale_by_id(sale_id=sale_id)
        return KitShopSaleDetailView(
            sale_id=sale.sale_id,
            company_id=sale.company_id,
            shop_id=sale.shop_id,
            device_id=sale.device_id,
            sale_datetime=parse_kit_datetime(sale.sale_datetime),
            positions=tuple(sale.positions),
        )

    @beartype
    def shop_name(self, shop_id: int) -> str | None:
        return self.client.shop_name(shop_id)

    @beartype
    def vendor_code(self, product_id: int) -> str | None:
        return self.client.vendor_code(product_id)


__all__ = [
    "KitShopSaleDetailView",
    "KitShopSaleListItemView",
    "KitShopSalesGatewayAdapter",
]
