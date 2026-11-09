from __future__ import annotations

from beartype import beartype

from src.application.matrix_automation.snack_machine_layout import SnackMachineLayoutCell
from src.application.product_identity import DomainProduct
from src.application.product_identity.ports import DomainProductStore


@beartype
def kit_product_code(
    cell: SnackMachineLayoutCell,
    products: DomainProductStore | None,
) -> str | None:
    domain_id = (cell.domain_product_id or "").strip() or None
    if domain_id is not None:
        if products is None:
            return None
        product: DomainProduct | None = products.get(domain_id)
        if product is None:
            return None
        code = (product.catalog_code or "").strip() or None
        return code
    code = (cell.product_code or "").strip() or None
    return code


@beartype
def skipped_product_name(
    cell: SnackMachineLayoutCell,
    products: DomainProductStore | None,
) -> str | None:
    domain_id = (cell.domain_product_id or "").strip() or None
    if domain_id is None:
        return None
    if products is None:
        return "Товар не найден"
    product: DomainProduct | None = products.get(domain_id)
    if product is None:
        return "Товар не найден"
    if not (product.catalog_code or "").strip():
        return product.name
    return None
