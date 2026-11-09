from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions.ports import ProductCodeResolver
from src.application.sheets.ports import ProductSpecByCodeResolver
from src.domain.product_catalog import ProductSpec
from src.infrastructure.integrations.google.sheets.product_catalog_source import (
    GoogleSheetsProductCatalogSource,
)


@beartype
@dataclass(slots=True)
class GoogleSheetsProductSpecByCodeResolver(ProductSpecByCodeResolver):
    catalog_source: GoogleSheetsProductCatalogSource

    @beartype
    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None:
        code = product_code.strip().casefold()
        if not code:
            raise ValueError("Product code must not be empty")
        return self.catalog_source.get_code_to_spec().get(code)

    @beartype
    def resolve_by_code(self, product_code: str) -> ProductSpec:
        spec = self.try_resolve_by_code(product_code)
        if spec is None:
            raise ValueError(f"Product spec not found for code {product_code.strip()!r}")
        return spec


@beartype
@dataclass(slots=True)
class GoogleSheetsProductCodeResolver(ProductCodeResolver):
    catalog_source: GoogleSheetsProductCatalogSource

    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec:
        normalized_name = product_name.strip().casefold()
        if not normalized_name:
            raise ValueError("Product name must not be empty")
        name_to_spec = self.catalog_source.get_name_to_spec()
        try:
            return name_to_spec[normalized_name]
        except KeyError as error:
            raise ValueError(
                f"Product spec not found for name {product_name.strip()!r}",
            ) from error
