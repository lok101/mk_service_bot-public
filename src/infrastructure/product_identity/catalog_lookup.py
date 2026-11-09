from __future__ import annotations

from beartype import beartype

from src.application.product_identity import CatalogProduct, catalog_code_key
from src.application.reference_data import MsEntityKind, ReferenceDataProvider

_SEARCH_LIMIT = 50


@beartype
class SnapshotCatalogProductLookup:
    def __init__(self, provider: ReferenceDataProvider) -> None:
        self._provider = provider

    @beartype
    def get(self, code: str) -> CatalogProduct | None:
        catalog = self._provider.product_catalog_or_none()
        if catalog is None:
            return None
        entry = catalog.by_code.get(code.strip())
        if entry is None or entry.entity_kind is not MsEntityKind.PRODUCT:
            return None
        return CatalogProduct(code=entry.code, name=entry.name, archived=entry.archived)

    @beartype
    def search(self, query: str) -> tuple[CatalogProduct, ...]:
        catalog = self._provider.product_catalog_or_none()
        if catalog is None:
            return ()
        needle = query.strip().casefold()
        found: list[CatalogProduct] = []
        for entry in catalog.by_code.values():
            if entry.entity_kind is not MsEntityKind.PRODUCT:
                continue
            code_matches = needle in entry.code.casefold()
            name_matches = needle in entry.name.casefold()
            if needle and not code_matches and not name_matches:
                continue
            found.append(
                CatalogProduct(code=entry.code, name=entry.name, archived=entry.archived),
            )
            if len(found) == _SEARCH_LIMIT:
                break
        return tuple(found)

    @beartype
    def products(self) -> tuple[CatalogProduct, ...]:
        catalog = self._provider.product_catalog_or_none()
        if catalog is None:
            return ()
        return tuple(
            CatalogProduct(code=entry.code, name=entry.name, archived=entry.archived)
            for entry in catalog.by_code.values()
            if entry.entity_kind is MsEntityKind.PRODUCT
        )

    @beartype
    def number_collides(self, number: str) -> bool:
        catalog = self._provider.product_catalog_or_none()
        if catalog is None:
            return False
        return any(
            entry.entity_kind is MsEntityKind.PRODUCT and catalog_code_key(entry.code) == number
            for entry in catalog.by_code.values()
        )
