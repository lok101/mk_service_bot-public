from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.sheets.ports import ProductSpecByCodeResolver
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)


@beartype
@dataclass(frozen=True, slots=True)
class PassThroughProductSpecByCodeResolver(ProductSpecByCodeResolver):
    """Dev fallback when PRODUCT_CATALOG_* is not configured.

    Accepts any non-empty product code without catalog lookup.
    Do not use in prod paths that require real Sheets catalog validation.
    """

    @beartype
    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None:
        normalized = product_code.strip()
        if not normalized:
            raise ValueError("Product code must not be empty")
        unit = ProductUnit.GRAM
        return ProductSpec(
            product_code=normalized,
            name=normalized,
            unit=unit,
            pack_size=Decimal("1"),
            min_stock=None,
            max_stock=None,
            allow_fraction=True,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        )

    @beartype
    def resolve_by_code(self, product_code: str) -> ProductSpec:
        spec = self.try_resolve_by_code(product_code)
        assert spec is not None  # pass-through never returns None
        return spec


@beartype
@dataclass(frozen=True, slots=True)
class MappingProductSpecByCodeResolver(ProductSpecByCodeResolver):
    specs_by_code: dict[str, ProductSpec]

    @beartype
    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None:
        code = product_code.strip().casefold()
        if not code:
            raise ValueError("Product code must not be empty")
        return self.specs_by_code.get(code)

    @beartype
    def resolve_by_code(self, product_code: str) -> ProductSpec:
        spec = self.try_resolve_by_code(product_code)
        if spec is None:
            raise ValueError(f"Product spec not found for code {product_code.strip()!r}")
        return spec
