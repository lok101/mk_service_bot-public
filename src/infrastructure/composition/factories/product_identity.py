from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_inventory_policy import (
    FormInventoryPolicyStore,
    MemoryFormInventoryPolicyStore,
)
from src.application.product_identity import (
    DomainProductResolve,
    KitShopSaleResolve,
    SyncProcurementMirror,
    resolve_kit_shop_sale_code,
    resolve_sale_code,
)
from src.application.product_identity.border_registration import (
    BorderRegistrationStore,
    MemoryBorderRegistrationStore,
)
from src.application.product_identity.ports import (
    DomainProductStore,
    ProcurementAttributesFetcher,
    ProcurementMirrorStore,
)
from src.application.reference_data import ReferenceDataProvider
from src.config.domain_product_identity import DomainProductIdentitySettings
from src.config.mongodb import MongoSettings
from src.config.product_procurement_mirror import ProductProcurementMirrorSettings
from src.config.settings import Settings
from src.infrastructure.form_inventory_policy import MongoFormInventoryPolicyStore
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.moysklad.purchase_prices.http_client import (
    MoySkladPurchasePricesHttpClient,
)
from src.infrastructure.product_identity.catalog_lookup import SnapshotCatalogProductLookup
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.product_identity.memory_store import MemoryDomainProductStore
from src.infrastructure.product_identity.mongo_border_registration_store import (
    MongoBorderRegistrationStore,
)
from src.infrastructure.product_identity.mongo_procurement_mirror_store import (
    MongoProcurementMirrorStore,
)
from src.infrastructure.product_identity.mongo_store import MongoDomainProductStore
from src.infrastructure.product_identity.procurement_attributes_fetcher import (
    MoySkladProcurementAttributesFetcher,
)
from src.infrastructure.product_identity.procurement_mirror_worker import (
    ProductProcurementMirrorSyncWorker,
)

_NoOpClose = Callable[[], None]


@beartype
def build_domain_product_store(
    mongodb: MongoSettings,
    identity: DomainProductIdentitySettings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> DomainProductStore:
    if mongodb.is_configured:
        return MongoDomainProductStore.from_settings(mongodb, identity, client=client)
    return MemoryDomainProductStore()


@beartype
def build_form_inventory_policy_store(
    mongodb: MongoSettings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> FormInventoryPolicyStore:
    if mongodb.is_configured:
        return MongoFormInventoryPolicyStore.from_settings(mongodb, client=client)
    return MemoryFormInventoryPolicyStore()


@beartype
def build_border_registration_store(
    mongodb: MongoSettings,
    identity: DomainProductIdentitySettings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> BorderRegistrationStore:
    if mongodb.is_configured:
        return MongoBorderRegistrationStore.from_settings(mongodb, identity, client=client)
    return MemoryBorderRegistrationStore()


@beartype
def build_procurement_mirror_store(
    mongodb: MongoSettings,
    mirror_settings: ProductProcurementMirrorSettings,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> ProcurementMirrorStore:
    if mongodb.is_configured:
        return MongoProcurementMirrorStore.from_settings(
            mongodb,
            mirror_settings,
            client=client,
        )
    return MemoryProcurementMirrorStore()


@beartype
def build_procurement_mirror_sync(
    *,
    enabled: bool,
    products: DomainProductStore,
    mirrors: ProcurementMirrorStore,
    fetcher: ProcurementAttributesFetcher,
    supply_concurrency: int,
) -> SyncProcurementMirror:
    return SyncProcurementMirror(
        enabled=enabled,
        products=products,
        mirrors=mirrors,
        fetcher=fetcher,
        clock=lambda: datetime.now(UTC),
        supply_concurrency=supply_concurrency,
    )


@beartype
def build_procurement_mirror_worker(
    settings: Settings,
    *,
    domain_product_store: DomainProductStore,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
    include_moysklad_http: bool = True,
) -> tuple[
    ProductProcurementMirrorSyncWorker | None,
    ProcurementMirrorStore | None,
    SyncProcurementMirror | None,
    _NoOpClose,
]:
    # Admin (app) reads last-buy from the store; Remap sync/cron only on effects.
    if not settings.product_procurement_mirror.enabled:
        return None, None, None, lambda: None
    mirror_settings = settings.product_procurement_mirror
    store = build_procurement_mirror_store(
        settings.mongodb,
        mirror_settings,
        client=mongo_client,
    )
    if not include_moysklad_http or not settings.moysklad.is_configured:
        return None, store, None, lambda: None
    http_client = MoySkladPurchasePricesHttpClient.from_settings(
        settings.moysklad,
        supply_fetch_concurrency=mirror_settings.supply_concurrency,
        package_quantity_attr_id=mirror_settings.attr_package_quantity_id,
        supplier_product_name_attr_id=mirror_settings.attr_supplier_product_name_id,
    )
    fetcher = MoySkladProcurementAttributesFetcher(client=http_client)
    sync = build_procurement_mirror_sync(
        enabled=True,
        products=domain_product_store,
        mirrors=store,
        fetcher=fetcher,
        supply_concurrency=mirror_settings.supply_concurrency,
    )
    worker = ProductProcurementMirrorSyncWorker(
        sync=sync,
        interval_seconds=mirror_settings.sync_interval_seconds,
    )
    return worker, store, sync, http_client.close


@beartype
def build_catalog_product_lookup(
    provider: ReferenceDataProvider,
) -> SnapshotCatalogProductLookup:
    return SnapshotCatalogProductLookup(provider)


@beartype
def build_domain_product_resolver(
    settings: Settings,
    provider: ReferenceDataProvider,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
) -> Callable[[str], DomainProductResolve] | None:
    if not settings.domain_product_identity.enabled:
        return None
    store = build_domain_product_store(
        settings.mongodb,
        settings.domain_product_identity,
        client=client,
    )
    lookup = build_catalog_product_lookup(provider)

    def resolve(code: str) -> DomainProductResolve:
        return resolve_sale_code(code, store=store, lookup=lookup)

    return resolve


@beartype
def build_domain_product_kit_shop_resolver(
    settings: Settings,
    provider: ReferenceDataProvider,
    *,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
) -> Callable[[str], KitShopSaleResolve] | None:
    if not settings.domain_product_identity.enabled:
        return None
    store = build_domain_product_store(
        settings.mongodb,
        settings.domain_product_identity,
        client=client,
    )
    lookup = build_catalog_product_lookup(provider)

    def resolve(code: str) -> KitShopSaleResolve:
        return resolve_kit_shop_sale_code(code, store=store, lookup=lookup)

    return resolve
