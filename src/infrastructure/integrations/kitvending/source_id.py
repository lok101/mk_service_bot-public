from __future__ import annotations

from beartype import beartype

from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel


@beartype
def build_sale_source_id(sale: SaleModel) -> str:
    matrix_part = sale.matrix_id if sale.matrix_id is not None else 0
    return f"kit:{sale.vending_machine_id}:{sale.datetime_kit}:{sale.line}:{matrix_part}"


@beartype
def iter_raw_sales_with_source_ids(
    sales: list[SaleModel],
) -> list[tuple[SaleModel, str]]:
    return [(sale, build_sale_source_id(sale)) for sale in sales]
