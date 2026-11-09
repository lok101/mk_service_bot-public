from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype


@runtime_checkable
class SellableProductCodeCatalog(Protocol):
    """Sellable assortment membership for daily demand (Mongo product_catalog)."""

    @beartype
    def ready(self) -> bool:
        """True when snapshot present and has ≥1 MS product (entity_kind=product)."""
        ...

    @beartype
    def contains(self, code: str) -> bool:
        """Strip-exact membership in by_code (not vitrine casefold)."""
        ...
