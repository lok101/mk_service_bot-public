from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry


@beartype
@dataclass(slots=True)
class InMemoryMatrixSkuCatalogStore:
    _by_code: dict[str, MatrixSkuCatalogEntry] = field(default_factory=dict)

    def get(self, product_code: str) -> MatrixSkuCatalogEntry | None:
        return self._by_code.get(product_code)

    def upsert(self, entry: MatrixSkuCatalogEntry) -> None:
        self._by_code[entry.product_code] = entry

    def list_all(self) -> tuple[MatrixSkuCatalogEntry, ...]:
        return tuple(self._by_code.values())
