from __future__ import annotations

from beartype import beartype

from src.application.product_identity.procurement_mirror import ProcurementMirror


@beartype
class MemoryProcurementMirrorStore:
    def __init__(self) -> None:
        self._by_code: dict[str, ProcurementMirror] = {}

    @beartype
    def get(self, catalog_code: str) -> ProcurementMirror | None:
        return self._by_code.get(catalog_code)

    @beartype
    def upsert(self, mirror: ProcurementMirror) -> None:
        self._by_code[mirror.catalog_code] = mirror

    @beartype
    def delete(self, catalog_code: str) -> None:
        self._by_code.pop(catalog_code, None)

    @beartype
    def codes(self) -> tuple[str, ...]:
        return tuple(self._by_code)
