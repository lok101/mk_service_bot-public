from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.reference_data import ReferenceDataProvider
from src.application.sheets import ParsedProductCatalog
from src.domain.product_catalog import ProductSpec


@beartype
def code_index_from_catalog(catalog: ParsedProductCatalog) -> dict[str, ProductSpec]:
    code_to_spec: dict[str, ProductSpec] = {}
    for key in catalog.code_keys:
        try:
            spec = catalog.lookup[key]
        except KeyError as error:
            raise ValueError(
                f"Product catalog code key missing from lookup: {key!r}",
            ) from error
        code_to_spec[key] = spec
    return code_to_spec


@beartype
@dataclass(slots=True)
class GoogleSheetsProductCatalogSource:
    provider: ReferenceDataProvider

    @beartype
    def get_name_to_spec(self) -> dict[str, ProductSpec]:
        catalog = self.provider.product_vitrine_or_none()
        if catalog is None:
            return {}
        return {
            name.casefold(): spec
            for name, spec in catalog.lookup.items()
            if name not in catalog.code_keys
        }

    @beartype
    def get_code_to_spec(self) -> dict[str, ProductSpec]:
        catalog = self.provider.product_vitrine_or_none()
        if catalog is None:
            return {}
        return code_index_from_catalog(catalog)
