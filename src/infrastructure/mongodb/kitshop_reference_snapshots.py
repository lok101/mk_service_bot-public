from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.config.mongodb import MongoSettings
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshot,
    KitShopSnapshotGroup,
    KitShopSnapshotProduct,
    KitShopSnapshotShop,
)
from src.infrastructure.mongodb.connection import resolve_collection


@beartype
def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@runtime_checkable
class KitShopReferenceSnapshotCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@beartype
def _snapshot_to_document(snapshot: KitShopReferenceSnapshot) -> dict[str, Any]:
    return {
        "_id": snapshot.kit_company_id,
        "kit_company_id": snapshot.kit_company_id,
        "refreshed_at": snapshot.refreshed_at,
        "groups": [
            {"group_id": item.group_id, "group_name": item.group_name} for item in snapshot.groups
        ],
        "shops": [
            {
                "shop_id": item.shop_id,
                "shop_name": item.shop_name,
                "product_base_template_id": item.product_base_template_id,
            }
            for item in snapshot.shops
        ],
        "products": [
            {
                "product_id": item.product_id,
                "vendor_code": item.vendor_code,
                "product_name": item.product_name,
                "is_deleted": item.is_deleted,
            }
            for item in snapshot.products
        ],
    }


@beartype
def _snapshot_from_document(document: dict[str, Any]) -> KitShopReferenceSnapshot:
    kit_company_id = document.get("kit_company_id")
    refreshed_at = document.get("refreshed_at")
    groups_raw = document.get("groups", [])
    shops_raw = document.get("shops", [])
    products_raw = document.get("products", [])
    if not isinstance(kit_company_id, int):
        raise ValueError("kit_company_id must be int")
    if not isinstance(refreshed_at, datetime):
        raise ValueError("refreshed_at must be datetime")
    refreshed_at = _as_aware_utc(refreshed_at)
    if not isinstance(groups_raw, list):
        raise ValueError("groups must be list")
    if not isinstance(shops_raw, list):
        raise ValueError("shops must be list")
    if not isinstance(products_raw, list):
        raise ValueError("products must be list")
    groups = tuple(
        KitShopSnapshotGroup(
            group_id=int(item["group_id"]),
            group_name=str(item["group_name"]),
        )
        for item in groups_raw
        if isinstance(item, dict)
    )
    shops = tuple(
        KitShopSnapshotShop(
            shop_id=int(item["shop_id"]),
            shop_name=str(item["shop_name"]),
            product_base_template_id=(
                int(item["product_base_template_id"])
                if item.get("product_base_template_id") is not None
                else None
            ),
        )
        for item in shops_raw
        if isinstance(item, dict)
    )
    products = tuple(
        KitShopSnapshotProduct(
            product_id=int(item["product_id"]),
            vendor_code=(str(item["vendor_code"]) if item.get("vendor_code") is not None else None),
            product_name=str(item["product_name"]),
            is_deleted=bool(item.get("is_deleted", False)),
        )
        for item in products_raw
        if isinstance(item, dict)
    )
    return KitShopReferenceSnapshot(
        kit_company_id=kit_company_id,
        refreshed_at=refreshed_at,
        groups=groups,
        shops=shops,
        products=products,
    )


@beartype
class MongoKitShopReferenceSnapshotStore:
    def __init__(self, collection: KitShopReferenceSnapshotCollection) -> None:
        self._collection = collection

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: Any = None,
    ) -> MongoKitShopReferenceSnapshotStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.kitshop_reference_snapshots_collection,
            owner="MongoKitShopReferenceSnapshotStore",
            client=client,
        )
        return cls(collection)

    @beartype
    def get(self, kit_company_id: int) -> KitShopReferenceSnapshot | None:
        document = self._collection.find_one({"_id": kit_company_id})
        if document is None:
            return None
        return _snapshot_from_document(document)

    @beartype
    def replace(self, snapshot: KitShopReferenceSnapshot) -> None:
        self._collection.replace_one(
            {"_id": snapshot.kit_company_id},
            _snapshot_to_document(snapshot),
            upsert=True,
        )
