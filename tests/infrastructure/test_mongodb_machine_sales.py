from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.mongodb.machine_sales import (
    MongoMachineSalesStore,
    machine_sale_from_document,
    machine_sale_to_document,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_MACHINE_ID = MachineId("vm-01")
_OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 6, 8, 11, 0, tzinfo=UTC)


def _sale(
    *,
    source_id: str,
    occurred_at: datetime,
    quantity: Decimal = Decimal("1"),
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE_ID,
        product_code="coffee-1",
        quantity=quantity,
        occurred_at=occurred_at,
        ingested_at=_INGESTED,
    )


def test_old_sale_document_reads_missing_domain_product_id_as_empty() -> None:
    sale = _sale(source_id="old", occurred_at=_INSIDE)
    document = machine_sale_to_document(sale)
    document.pop("domain_product_id", None)
    loaded = machine_sale_from_document(document)
    assert loaded.domain_product_id == ""


def test_insert_if_absent_keeps_first_domain_product_id() -> None:
    store = InMemoryMachineSalesStore()
    first = _sale(source_id="same", occurred_at=_INSIDE)
    first = replace(first, domain_product_id="prod-1", product_code="2311")
    second = replace(first, domain_product_id="prod-2", product_code="9999")
    assert store.insert_if_absent(first) is True
    assert store.insert_if_absent(second) is False
    kept = store._by_source_id["same"]
    assert kept.domain_product_id == "prod-1"
    assert kept.product_code == "2311"


def test_sale_document_roundtrips_domain_product_id() -> None:
    empty = _sale(source_id="empty", occurred_at=_INSIDE)
    empty_document = machine_sale_to_document(empty)
    assert "domain_product_id" not in empty_document

    filled = replace(empty, domain_product_id="prod-1")
    document = machine_sale_to_document(filled)
    assert document["domain_product_id"] == "prod-1"
    loaded = machine_sale_from_document(document)
    assert loaded.domain_product_id == "prod-1"


def test_insert_if_absent_returns_true_then_false() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    sale = _sale(source_id="kv-1", occurred_at=_INSIDE)

    assert store.insert_if_absent(sale) is True
    assert store.insert_if_absent(sale) is False


def test_insert_if_absent_enforces_unique_source_id() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="kv-1", occurred_at=_INSIDE))

    with pytest.raises(DuplicateKeyError):
        collection.insert_one(
            {
                "source_id": "kv-1",
                "machine_id": _MACHINE_ID.value,
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": _INSIDE,
                "ingested_at": _INGESTED,
            },
        )


def test_find_in_window_respects_half_open_bounds() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="at-open", occurred_at=_OPENED))
    store.insert_if_absent(_sale(source_id="inside", occurred_at=_INSIDE))
    store.insert_if_absent(_sale(source_id="at-close", occurred_at=_CLOSED))

    window = store.find_in_window(
        _MACHINE_ID,
        opened_at=_OPENED,
        closed_at=_CLOSED,
    )

    source_ids = {sale.source_id for sale in window}
    assert source_ids == {"inside", "at-close"}


def test_find_in_window_filters_by_machine_id() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="vm-01", occurred_at=_INSIDE))
    store.insert_if_absent(
        MachineSale(
            source_id="vm-02",
            machine_id=MachineId("vm-02"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
        ),
    )

    window = store.find_in_window(
        _MACHINE_ID,
        opened_at=_OPENED,
        closed_at=_CLOSED,
    )

    assert len(window) == 1
    assert window[0].source_id == "vm-01"


def test_load_global_cursor_returns_none_when_empty() -> None:
    client = mongomock.MongoClient()
    store = MongoMachineSalesStore.from_collection(
        client.db.machine_sales,
        cursor_collection=client.db.sales_ingest_cursors,
    )

    assert store.load_global_cursor() is None


def test_save_and_load_global_cursor_persists_watermark() -> None:
    client = mongomock.MongoClient()
    store = MongoMachineSalesStore.from_collection(
        client.db.machine_sales,
        cursor_collection=client.db.sales_ingest_cursors,
    )
    watermark = datetime(2026, 6, 7, 15, 30, tzinfo=UTC)

    store.save_global_cursor(watermark)

    assert store.load_global_cursor() == watermark


def test_load_global_cursor_uses_max_of_persisted_and_sales() -> None:
    client = mongomock.MongoClient()
    store = MongoMachineSalesStore.from_collection(
        client.db.machine_sales,
        cursor_collection=client.db.sales_ingest_cursors,
    )
    persisted = datetime(2026, 6, 7, 15, 30, tzinfo=UTC)
    later_sale = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
    store.save_global_cursor(persisted)
    store.insert_if_absent(_sale(source_id="later", occurred_at=later_sale))

    assert store.load_global_cursor() == later_sale


def test_last_occurred_at_returns_max_or_none() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)

    assert store.last_occurred_at(_MACHINE_ID) is None

    store.insert_if_absent(_sale(source_id="earlier", occurred_at=_INSIDE))
    store.insert_if_absent(_sale(source_id="later", occurred_at=_CLOSED))

    assert store.last_occurred_at(_MACHINE_ID) == _CLOSED


def test_machine_sale_round_trips_sale_kind() -> None:
    sale = MachineSale(
        source_id="kv-1",
        machine_id=_MACHINE_ID,
        product_code="2301",
        quantity=Decimal("1"),
        occurred_at=_INSIDE,
        ingested_at=_INGESTED,
        sale_kind="coffee",
    )
    store = MongoMachineSalesStore.from_collection(mongomock.MongoClient().db.machine_sales)
    store.insert_if_absent(sale)
    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].sale_kind == "coffee"


def test_machine_sale_defaults_sale_kind_unknown_for_legacy_documents() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    collection.insert_one(
        {
            "source_id": "legacy-1",
            "machine_id": _MACHINE_ID.value,
            "product_code": "coffee-1",
            "quantity": "1",
            "occurred_at": _INSIDE,
            "ingested_at": _INGESTED,
        },
    )
    store = MongoMachineSalesStore.from_collection(collection)
    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].sale_kind == "unknown"


def test_set_resolve_status_persists_on_existing_sale() -> None:
    store = MongoMachineSalesStore.from_collection(mongomock.MongoClient().db.machine_sales)
    store.insert_if_absent(_sale(source_id="kv-1", occurred_at=_INSIDE))

    store.set_resolve_status("kv-1", "unresolved_matrix")

    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert len(loaded) == 1
    assert loaded[0].resolve_status == "unresolved_matrix"


def test_set_resolve_status_missing_source_raises_key_error() -> None:
    store = MongoMachineSalesStore.from_collection(mongomock.MongoClient().db.machine_sales)

    with pytest.raises(KeyError, match="machine sale not found"):
        store.set_resolve_status("missing", "resolved")


def test_insert_persists_price_decimal() -> None:
    sale = MachineSale(
        source_id="s-price",
        machine_id=MachineId("m-1"),
        product_code="P1",
        quantity=Decimal("1"),
        occurred_at=_INSIDE,
        ingested_at=_INGESTED,
        price=Decimal("99.00"),
    )
    doc = machine_sale_to_document(sale)
    assert doc["price"] == "99.00"
    roundtrip = machine_sale_from_document(doc)
    assert roundtrip.price == Decimal("99.00")


def test_machine_sale_from_document_missing_price_is_none() -> None:
    doc = machine_sale_to_document(
        MachineSale(
            source_id="s-legacy",
            machine_id=MachineId("m-1"),
            product_code="P1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
        )
    )
    doc.pop("price", None)
    assert machine_sale_from_document(doc).price is None


def test_set_price_if_absent_sets_price_on_doc_without_price() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="kv-1", occurred_at=_INSIDE))

    assert store.set_price_if_absent("kv-1", Decimal("15.50")) is True

    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].price == Decimal("15.50")


def test_set_price_if_absent_does_not_overwrite_existing_price() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-1",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            price=Decimal("99.00"),
        )
    )

    assert store.set_price_if_absent("kv-1", Decimal("1.00")) is False

    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].price == Decimal("99.00")


def test_set_price_if_absent_returns_false_for_unknown_source_id() -> None:
    store = MongoMachineSalesStore.from_collection(mongomock.MongoClient().db.machine_sales)

    assert store.set_price_if_absent("missing", Decimal("1.00")) is False


def test_min_occurred_at_missing_price_returns_none_when_all_priced() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-1",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            price=Decimal("1.00"),
        )
    )

    assert store.min_occurred_at_missing_price() is None


def test_min_occurred_at_missing_price_returns_earliest_without_price() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="later", occurred_at=_CLOSED))
    store.insert_if_absent(_sale(source_id="earlier", occurred_at=_INSIDE))
    store.insert_if_absent(
        MachineSale(
            source_id="priced",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_OPENED,
            ingested_at=_INGESTED,
            price=Decimal("1.00"),
        )
    )

    assert store.min_occurred_at_missing_price() == _INSIDE


def test_find_missing_price_before_excludes_priced_and_out_of_window() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    cutover = datetime(2026, 6, 6, 0, 0, tzinfo=UTC)
    store.insert_if_absent(_sale(source_id="in-window", occurred_at=_INSIDE))
    store.insert_if_absent(_sale(source_id="after-cutover", occurred_at=_CLOSED))
    store.insert_if_absent(
        MachineSale(
            source_id="already-priced",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            price=Decimal("1.00"),
        )
    )

    result = store.find_missing_price_before(cutover)

    assert [sale.source_id for sale in result] == ["in-window"]


def test_machine_sale_roundtrip_company_id() -> None:
    sale = MachineSale(
        source_id="kv-1",
        machine_id=_MACHINE_ID,
        product_code="coffee-1",
        quantity=Decimal("1"),
        occurred_at=_INSIDE,
        ingested_at=_INGESTED,
        company_id=42,
    )
    document = machine_sale_to_document(sale)
    assert document["company_id"] == 42
    loaded = machine_sale_from_document(document)
    assert loaded.company_id == 42


def test_machine_sale_from_document_without_company_id_is_none() -> None:
    sale = _sale(source_id="kv-1", occurred_at=_INSIDE)
    document = machine_sale_to_document(sale)
    document.pop("company_id", None)
    assert machine_sale_from_document(document).company_id is None


def test_patch_company_id_if_missing_sets_when_absent() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="kv-1", occurred_at=_INSIDE))

    assert store.patch_company_id_if_missing("kv-1", 42) is True
    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].company_id == 42


def test_patch_company_id_if_missing_does_not_overwrite() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-1",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            company_id=99,
        )
    )

    assert store.patch_company_id_if_missing("kv-1", 1) is False
    loaded = store.find_in_window(_MACHINE_ID, opened_at=_OPENED, closed_at=_CLOSED)
    assert loaded[0].company_id == 99


def test_patch_company_id_if_missing_returns_false_for_unknown_source_id() -> None:
    store = MongoMachineSalesStore.from_collection(mongomock.MongoClient().db.machine_sales)
    assert store.patch_company_id_if_missing("missing", 42) is False


def test_list_with_company_id_filters_and_orders() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    store.insert_if_absent(_sale(source_id="no-id", occurred_at=_INSIDE))
    store.insert_if_absent(
        MachineSale(
            source_id="later",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_CLOSED,
            ingested_at=_INGESTED,
            company_id=2,
        )
    )
    store.insert_if_absent(
        MachineSale(
            source_id="earlier",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_OPENED,
            ingested_at=_INGESTED,
            company_id=1,
        )
    )
    store.insert_if_absent(
        MachineSale(
            source_id="other-vm",
            machine_id=MachineId("vm-02"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            company_id=9,
        )
    )
    listed = store.list_with_company_id(_MACHINE_ID)
    assert [sale.source_id for sale in listed] == ["earlier", "later"]
    assert [sale.company_id for sale in listed] == [1, 2]
