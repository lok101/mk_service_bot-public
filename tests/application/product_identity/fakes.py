from __future__ import annotations

from decimal import Decimal

from src.application.product_identity.models import (
    CatalogProduct,
    DomainProduct,
    DomainProductConflict,
    catalog_codes_of,
)
from src.application.product_identity.number import catalog_code_key
from src.domain.product_catalog import ProductUnit

COFFEE_INGREDIENT_PACKAGING: dict[str, ProductUnit | Decimal] = {
    "unit": ProductUnit.GRAM,
    "pack_size": Decimal("1000"),
}


class FakeDomainProductStore:
    def __init__(self) -> None:
        self.writes = 0
        self.fail_number_once: str | None = None
        self.fail_catalog_code_once: str | None = None
        self._by_id: dict[str, DomainProduct] = {}

    def insert(self, product: DomainProduct) -> None:
        if self.fail_number_once is not None and product.number == self.fail_number_once:
            self.fail_number_once = None
            raise DomainProductConflict("number")
        self._reject_conflicts(product, skip_id=None)
        self._by_id[product.domain_product_id] = product
        self.writes += 1

    def save(self, product: DomainProduct) -> None:
        if (
            self.fail_catalog_code_once is not None
            and product.catalog_code == self.fail_catalog_code_once
        ):
            self.fail_catalog_code_once = None
            raise DomainProductConflict("catalog_code")
        self._reject_conflicts(product, skip_id=product.domain_product_id)
        self._by_id[product.domain_product_id] = product
        self.writes += 1

    def get(self, domain_product_id: str) -> DomainProduct | None:
        return self._by_id.get(domain_product_id)

    def get_by_number(self, number: str) -> DomainProduct | None:
        for product in self._by_id.values():
            if product.number == number:
                return product
        return None

    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None:
        for product in self._by_id.values():
            if catalog_code in catalog_codes_of(product):
                return product
            if product.legacy_ms_code == catalog_code:
                return product
        return None

    def list_visible(self) -> tuple[DomainProduct, ...]:
        return tuple(product for product in self._by_id.values() if not product.hidden)

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


class FakeCatalogLookup:
    def __init__(
        self,
        cards: tuple[CatalogProduct, ...] = (),
        *,
        search_limit: int | None = None,
    ) -> None:
        self.cards: dict[str, CatalogProduct] = {card.code: card for card in cards}
        self.search_limit = search_limit

    def get(self, code: str) -> CatalogProduct | None:
        return self.cards.get(code)

    def search(self, query: str) -> tuple[CatalogProduct, ...]:
        needle = query.strip().casefold()
        if needle:
            found = tuple(
                card
                for card in self.cards.values()
                if needle in card.code.casefold() or needle in card.name.casefold()
            )
        else:
            found = tuple(self.cards.values())
        if self.search_limit is None:
            return found
        return found[: self.search_limit]

    def products(self) -> tuple[CatalogProduct, ...]:
        return tuple(self.cards.values())

    def number_collides(self, number: str) -> bool:
        return any(catalog_code_key(code) == number for code in self.cards)
