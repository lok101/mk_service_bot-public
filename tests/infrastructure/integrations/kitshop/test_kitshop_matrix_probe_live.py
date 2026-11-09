from __future__ import annotations

from decimal import Decimal

import pytest

from src.config.kitshop import KitShopSettings
from src.infrastructure.composition.factories import build_kitshop_client
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.http_client import KitShopApiClient
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)


def _probe_client() -> KitShopApiClient:
    # Under pytest dotenv is disabled (`DEFAULT_ENV_FILE=None`); full `get_settings()`
    # requires Google Forms secrets. KitShopSettings defaults + kit_platform_accounts.json.
    built = build_kitshop_client(
        KitShopSettings(),
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    if not isinstance(built, KitShopHttpClient):
        pytest.skip("Kit Shop client is not configured")
    return built.api


@pytest.mark.kitshop_matrix_live
def test_probe_799_remove_product_and_add_command() -> None:
    api = _probe_client()
    shops = [shop for shop in api.get_shops() if shop.shop_name == "PROBE микромаркет [799]"]
    if len(shops) != 1:
        pytest.skip("PROBE микромаркет [799] is not the single matching shop")
    shop = shops[0]
    template_id = shop.product_base_template_id
    if template_id is None:
        pytest.fail("У магазина нет шаблона матрицы")
    template = api.get_product_base_template(template_id=template_id)
    showcases = [item for item in template.locations if item.location_type == 2]
    if len(showcases) != 1:
        pytest.fail("Нужна одна витрина")
    product = next(
        (
            item
            for item in api.get_products()
            if item.vendor_code == "PROBE01" and not item.is_deleted
        ),
        None,
    )
    if product is None:
        pytest.fail("Товар PROBE01 не найден в Kit Shop")
    groups = list(api.get_product_groups())
    if not groups:
        pytest.fail("Группа товара PROBE01 не найдена в Kit Shop")
    api.add_product_to_product_base_template(
        template_id=template_id,
        product_id=product.product_id,
        price_rub=Decimal("151"),
        category_id=groups[0].group_id,
        location_id=showcases[0].location_id,
    )
    api.remove_product_from_product_base_template(
        template_id=template_id,
        product_id=product.product_id,
    )
    api.add_product_to_product_base_template(
        template_id=template_id,
        product_id=product.product_id,
        price_rub=Decimal("151"),
        category_id=groups[0].group_id,
        location_id=showcases[0].location_id,
    )
    api.add_command(shop_id=shop.shop_id)
