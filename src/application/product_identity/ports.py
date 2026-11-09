from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.product_identity.models import CatalogProduct, DomainProduct
from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementMirror,
    ProcurementSupplySnapshot,
)


@runtime_checkable
class DomainProductStore(Protocol):
    @beartype
    def insert(self, product: DomainProduct) -> None: ...

    @beartype
    def save(self, product: DomainProduct) -> None: ...

    @beartype
    def get(self, domain_product_id: str) -> DomainProduct | None: ...

    @beartype
    def get_by_number(self, number: str) -> DomainProduct | None: ...

    @beartype
    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None: ...

    @beartype
    def list_visible(self) -> tuple[DomainProduct, ...]: ...

    @beartype
    def numbers(self) -> tuple[str, ...]: ...


@runtime_checkable
class CatalogProductLookup(Protocol):
    @beartype
    def get(self, code: str) -> CatalogProduct | None: ...

    @beartype
    def search(self, query: str) -> tuple[CatalogProduct, ...]: ...

    @beartype
    def products(self) -> tuple[CatalogProduct, ...]: ...

    @beartype
    def number_collides(self, number: str) -> bool: ...


@runtime_checkable
class ProcurementMirrorStore(Protocol):
    @beartype
    def get(self, catalog_code: str) -> ProcurementMirror | None: ...

    @beartype
    def upsert(self, mirror: ProcurementMirror) -> None: ...

    @beartype
    def delete(self, catalog_code: str) -> None: ...

    @beartype
    def codes(self) -> tuple[str, ...]: ...


@runtime_checkable
class ProcurementAttributesFetcher(Protocol):
    @beartype
    def fetch(self, catalog_code: str) -> ProcurementSupplySnapshot | ProcurementFetchFailed: ...
