from __future__ import annotations

from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.planogram import MicromarketPlanogram
from src.application.micromarket_loading.shop_list_publish_journal import ShopListIntendedLine
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading import MicromarketDeviceStock


@beartype
def build_shop_list_intended_lines(
    doc: MicromarketPlanogram,
    products: DomainProductStore | None,
    stock: MicromarketDeviceStock | None = None,
) -> tuple[ShopListIntendedLine, ...]:
    """Intended showcase lines for journal diff (publishable + availability_off).

    До merge LOK-314 factual zero исключается из Kit payload, но остаётся в
    intended с ``availability_off=True`` → ``disabled_product_codes``.
    """
    lines: list[ShopListIntendedLine] = []
    for line in doc.lines:
        if not line.active:
            continue
        if not line.domain_product_id:
            continue
        product = products.get(line.domain_product_id) if products is not None else None
        if product is None:
            continue
        if line.kit_group_id is None:
            continue
        availability_off = stock is not None and stock.last_factual_qty(product.number) == Decimal(
            "0"
        )
        lines.append(
            ShopListIntendedLine(
                product_code=product.number,
                price_rub=line.price_rub,
                kit_group_id=line.kit_group_id,
                availability_off=availability_off,
            )
        )
    return tuple(lines)
