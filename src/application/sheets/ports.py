from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.product_catalog import ProductSpec


@runtime_checkable
class ProductSpecByCodeResolver(Protocol):
    @beartype
    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None: ...

    @beartype
    def resolve_by_code(self, product_code: str) -> ProductSpec: ...
