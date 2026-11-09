from __future__ import annotations

from beartype import beartype

from src.application.product_identity import DomainProduct, DomainProductConflict, catalog_codes_of


@beartype
class MemoryDomainProductStore:
    def __init__(self) -> None:
        self._by_id: dict[str, DomainProduct] = {}

    @beartype
    def insert(self, product: DomainProduct) -> None:
        self._reject_conflicts(product, skip_id=None)
        self._by_id[product.domain_product_id] = product

    @beartype
    def save(self, product: DomainProduct) -> None:
        self._reject_conflicts(product, skip_id=product.domain_product_id)
        self._by_id[product.domain_product_id] = product

    @beartype
    def get(self, domain_product_id: str) -> DomainProduct | None:
        return self._by_id.get(domain_product_id)

    @beartype
    def get_by_number(self, number: str) -> DomainProduct | None:
        for product in self._by_id.values():
            if product.number == number:
                return product
        return None

    @beartype
    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None:
        for product in self._by_id.values():
            if catalog_code in catalog_codes_of(product):
                return product
            if product.legacy_ms_code == catalog_code:
                return product
        return None

    @beartype
    def list_visible(self) -> tuple[DomainProduct, ...]:
        return tuple(product for product in self._by_id.values() if not product.hidden)

    @beartype
    def numbers(self) -> tuple[str, ...]:
        return tuple(product.number for product in self._by_id.values())

    def _reject_conflicts(self, product: DomainProduct, *, skip_id: str | None) -> None:
        codes = set(catalog_codes_of(product))
        if product.legacy_ms_code:
            codes.add(product.legacy_ms_code)
        for existing in self._by_id.values():
            if existing.domain_product_id == skip_id:
                continue
            if existing.number == product.number:
                raise DomainProductConflict("number")
            existing_codes = set(catalog_codes_of(existing))
            if existing.legacy_ms_code:
                existing_codes.add(existing.legacy_ms_code)
            if codes & existing_codes:
                raise DomainProductConflict("catalog_code")
