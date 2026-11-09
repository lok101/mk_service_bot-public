from __future__ import annotations

from decimal import Decimal

import mongomock
import pytest

from src.application.product_identity.models import DomainProduct, DomainProductConflict
from src.domain.product_catalog import ProductUnit
from src.infrastructure.product_identity.memory_store import MemoryDomainProductStore
from src.infrastructure.product_identity.mongo_store import MongoDomainProductStore


def _product(
    *,
    number: str,
    catalog_code: str | None,
    domain_product_id: str = "prod-1",
    name: str = "Товар",
    hidden: bool = False,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=number,
        name=name,
        catalog_code=catalog_code,
        hidden=hidden,
    )


def test_mongo_number_is_unique() -> None:
    store = MongoDomainProductStore.from_collection(mongomock.MongoClient().db.domain_products)
    store.insert(_product(number="d-1", catalog_code=None))
    with pytest.raises(DomainProductConflict) as caught:
        store.insert(_product(number="d-1", catalog_code=None))
    assert caught.value.field == "number"


def test_mongo_catalog_code_is_unique_including_hidden() -> None:
    store = MongoDomainProductStore.from_collection(mongomock.MongoClient().db.domain_products)
    holder = _product(number="d-1", catalog_code="2311", hidden=True)
    store.insert(holder)
    with pytest.raises(DomainProductConflict) as caught:
        store.insert(_product(number="d-2", catalog_code="2311"))
    assert caught.value.field == "catalog_code"
    assert store.get_by_catalog_code("2311") == holder


def test_memory_catalog_code_is_unique_including_hidden() -> None:
    store = MemoryDomainProductStore()
    holder = _product(number="d-1", catalog_code="2311", hidden=True)
    store.insert(holder)
    with pytest.raises(DomainProductConflict) as caught:
        store.insert(_product(number="d-2", catalog_code="2311"))
    assert caught.value.field == "catalog_code"
    assert store.get_by_catalog_code("2311") == holder


def test_mongo_inserts_two_products_without_catalog_code() -> None:
    collection = mongomock.MongoClient().db.domain_products
    store = MongoDomainProductStore.from_collection(collection)
    first = _product(domain_product_id="a", number="d-1", catalog_code=None)
    second = _product(domain_product_id="b", number="d-2", catalog_code=None)
    store.insert(first)
    store.insert(second)
    assert store.get("a") == first
    assert store.get("b") == second
    stored = collection.find_one({"_id": "a"})
    assert stored is not None
    assert "catalog_code" not in stored


def test_mongo_roundtrips_coffee_ingredient_packaging() -> None:
    store = MongoDomainProductStore.from_collection(mongomock.MongoClient().db.domain_products)
    product = DomainProduct(
        domain_product_id="ing-pack",
        number="d-9",
        name="Молоко",
        catalog_code=None,
        hidden=False,
        kind="coffee_ingredient",
        unit=ProductUnit.MILLILITER,
        pack_size=Decimal("500"),
    )
    store.insert(product)
    loaded = store.get("ing-pack")
    assert loaded is not None
    assert loaded.unit is ProductUnit.MILLILITER
    assert loaded.pack_size == Decimal("500")


def test_mongo_list_visible_includes_documents_without_hidden_field() -> None:
    collection = mongomock.MongoClient().db.domain_products
    collection.insert_one(
        {
            "_id": "ing-1",
            "number": "d-1",
            "name": "Кофе",
            "kind": "coffee_ingredient",
        },
    )
    store = MongoDomainProductStore.from_collection(collection)
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].number == "d-1"


def test_mongo_save_rejects_catalog_code_held_by_another() -> None:
    store = MongoDomainProductStore.from_collection(mongomock.MongoClient().db.domain_products)
    holder = _product(
        domain_product_id="holder",
        number="d-1",
        catalog_code="2311",
        hidden=True,
    )
    store.insert(holder)
    store.insert(_product(domain_product_id="other", number="d-2", catalog_code=None))
    with pytest.raises(DomainProductConflict) as caught:
        store.save(_product(domain_product_id="other", number="d-2", catalog_code="2311"))
    assert caught.value.field == "catalog_code"
    store.save(holder)
    assert store.get_by_catalog_code("2311") == holder
