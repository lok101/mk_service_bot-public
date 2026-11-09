from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSnapshotGroup:
    group_id: int
    group_name: str


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSnapshotShop:
    shop_id: int
    shop_name: str
    product_base_template_id: int | None


@beartype
@dataclass(frozen=True, slots=True)
class KitShopSnapshotProduct:
    product_id: int
    vendor_code: str | None
    product_name: str
    is_deleted: bool


@beartype
@dataclass(frozen=True, slots=True)
class KitShopReferenceSnapshot:
    kit_company_id: int
    refreshed_at: datetime
    groups: tuple[KitShopSnapshotGroup, ...]
    shops: tuple[KitShopSnapshotShop, ...]
    products: tuple[KitShopSnapshotProduct, ...]


@runtime_checkable
class KitShopReferenceSnapshotStore(Protocol):
    def get(self, kit_company_id: int) -> KitShopReferenceSnapshot | None: ...

    def replace(self, snapshot: KitShopReferenceSnapshot) -> None: ...


@beartype
class InMemoryKitShopReferenceSnapshotStore:
    def __init__(self) -> None:
        self._by_company: dict[int, KitShopReferenceSnapshot] = {}

    def get(self, kit_company_id: int) -> KitShopReferenceSnapshot | None:
        return self._by_company.get(kit_company_id)

    def replace(self, snapshot: KitShopReferenceSnapshot) -> None:
        self._by_company[snapshot.kit_company_id] = snapshot
