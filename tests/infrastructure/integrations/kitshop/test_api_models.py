from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.sale import KitShopSale
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.parsing.datetime_kit import parse_kit_datetime


def test_parse_kit_datetime() -> None:
    dt = parse_kit_datetime("04.09.2026 15:30:00")
    assert dt == datetime(2026, 9, 4, 15, 30, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert dt.astimezone(UTC) == datetime(2026, 9, 4, 12, 30, 0, tzinfo=UTC)


def test_shop_model_has_shop_name() -> None:
    shop = KitShopShop.model_validate({"ShopId": 10, "ShopName": "Офис [701]", "CompanyId": 1})
    assert shop.shop_id == 10
    assert shop.shop_name == "Офис [701]"


def test_sale_detail_has_shop_id_not_shop_name() -> None:
    sale = KitShopSale.model_validate(
        {
            "SaleId": 100,
            "CompanyId": 1,
            "ShopId": 10,
            "DeviceId": 99,
            "SaleDateTime": "04.09.2026 15:30:00",
            "Positions": [
                {
                    "PositionId": 1,
                    "ProductId": 50,
                    "Quantity": 2,
                    "Price": 100,
                }
            ],
        }
    )
    assert sale.shop_id == 10
    assert not hasattr(sale, "shop_name") or getattr(sale, "shop_name", None) is None
    assert sale.positions[0].product_id == 50


def test_product_vendor_code_optional() -> None:
    p = KitShopProduct.model_validate(
        {"ProductId": 50, "ProductName": "Snack", "VendorCode": "2311"}
    )
    assert p.vendor_code == "2311"
