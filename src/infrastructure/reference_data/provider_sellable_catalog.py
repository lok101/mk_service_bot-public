from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.reference_data.ms_product_catalog import MsEntityKind
from src.application.reference_data.provider import ReferenceDataProvider


@beartype
@dataclass(frozen=True, slots=True)
class ProviderSellableProductCodeCatalog:
    provider: ReferenceDataProvider

    def ready(self) -> bool:
        catalog = self.provider.product_catalog_or_none()
        if catalog is None:
            return False
        return any(entry.entity_kind is MsEntityKind.PRODUCT for entry in catalog.by_code.values())

    def contains(self, code: str) -> bool:
        catalog = self.provider.product_catalog_or_none()
        if catalog is None:
            return False
        return code.strip() in catalog.by_code
