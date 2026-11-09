from __future__ import annotations

import mongomock

from src.application.product_identity.models import DomainProduct
from src.application.reference_data import ReferenceDataProvider
from src.config.domain_product_identity import DomainProductIdentitySettings
from src.config.mongodb import MongoSettings
from src.infrastructure.composition import factories
from src.infrastructure.composition.factories.product_identity import (
    build_catalog_product_lookup,
    build_domain_product_store,
)
from src.infrastructure.product_identity.catalog_lookup import SnapshotCatalogProductLookup
from src.infrastructure.product_identity.memory_store import MemoryDomainProductStore
from src.infrastructure.product_identity.mongo_store import MongoDomainProductStore


def test_factory_uses_memory_when_storage_is_not_configured() -> None:
    store = build_domain_product_store(MongoSettings(), DomainProductIdentitySettings())
    assert isinstance(store, MemoryDomainProductStore)


def test_factory_uses_named_collection_when_storage_is_configured() -> None:
    client = mongomock.MongoClient()
    mongodb = MongoSettings(uri="mongodb://localhost", database="identity_db")
    identity = DomainProductIdentitySettings()
    store = build_domain_product_store(mongodb, identity, client=client)
    assert isinstance(store, MongoDomainProductStore)
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code=None,
            hidden=False,
        ),
    )
    assert "domain_products" in client["identity_db"].list_collection_names()


def test_factory_builds_snapshot_lookup() -> None:
    lookup = build_catalog_product_lookup(ReferenceDataProvider())
    assert isinstance(lookup, SnapshotCatalogProductLookup)


def test_factory_names_are_reexported() -> None:
    assert factories.build_domain_product_store is build_domain_product_store
    assert factories.build_catalog_product_lookup is build_catalog_product_lookup
