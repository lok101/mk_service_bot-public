from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.sheets.ports import ProductSpecByCodeResolver
from src.application.technician_warehouse.ports import CatalogBaseQuantityResolver
from src.infrastructure.integrations.moysklad.quantities import from_moysklad_quantity


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladCatalogBaseQuantityResolver(CatalogBaseQuantityResolver):
    product_resolver: ProductSpecByCodeResolver

    @beartype
    def try_resolve_line(
        self,
        *,
        product_code: str,
        moysklad_quantity: Decimal,
    ) -> tuple[str, Decimal] | None:
        spec = self.product_resolver.try_resolve_by_code(product_code)
        if spec is None:
            return None
        return spec.product_code, from_moysklad_quantity(spec, moysklad_quantity)

    @beartype
    def resolve_line(
        self,
        *,
        product_code: str,
        moysklad_quantity: Decimal,
    ) -> tuple[str, Decimal]:
        resolved = self.try_resolve_line(
            product_code=product_code,
            moysklad_quantity=moysklad_quantity,
        )
        if resolved is None:
            raise ValueError(f"Product spec not found for code {product_code.strip()!r}")
        return resolved
