from __future__ import annotations

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
    import_domain_products,
    link_domain_product,
)
from src.application.product_identity.models import (
    AMBIGUOUS_NAME_TEXT,
    CARD_TAKEN_TEXT,
    CODE_MISSING_TEXT,
    EMPTY_NAME_TEXT,
    FILE_EMPTY_TEXT,
    FILE_UNREADABLE_TEXT,
    OTHER_CARD_TEXT,
    CatalogProduct,
    DomainProductImportFailure,
    DomainProductImportResult,
    DomainProductImportRow,
)


def test_import_text_constants() -> None:
    assert OTHER_CARD_TEXT == "У товара уже другая карточка."
    assert AMBIGUOUS_NAME_TEXT == "Несколько товаров с таким именем."
    assert FILE_UNREADABLE_TEXT == "Файл не читается."
    assert FILE_EMPTY_TEXT == "В файле нет строк товаров."


def test_import_row_and_result_models() -> None:
    row = DomainProductImportRow(line_number=2, name="Молоко", catalog_code="2311")
    failure = DomainProductImportFailure(
        line_number=3,
        name="",
        message=FILE_UNREADABLE_TEXT,
    )
    result = DomainProductImportResult(
        created=1,
        linked=1,
        unchanged=0,
        failures=(failure,),
    )
    assert row.catalog_code == "2311"
    assert result.failures[0].line_number == 3


def _rows(*pairs: tuple[int, str, str]) -> tuple[DomainProductImportRow, ...]:
    return tuple(
        DomainProductImportRow(line_number=line, name=name, catalog_code=code)
        for line, name, code in pairs
    )


def test_import_creates_product_without_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    result = import_domain_products(
        _rows((2, "Молоко", "")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.linked == 0
    assert result.unchanged == 0
    assert result.failures == ()
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].name == "Молоко"
    assert visible[0].catalog_code is None


def test_import_creates_and_links_when_code_free() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    result = import_domain_products(
        _rows((2, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.linked == 1
    assert store.list_visible()[0].catalog_code == "2311"


def test_import_repeat_counts_unchanged() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    rows = _rows((2, "Молоко", "2311"), (3, "Чай", ""))
    import_domain_products(rows, store=store, lookup=lookup)
    again = import_domain_products(rows, store=store, lookup=lookup)
    assert again.created == 0
    assert again.linked == 0
    assert again.unchanged == 2
    assert again.failures == ()
    assert len(store.list_visible()) == 2


def test_import_links_existing_unlinked_by_name() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    create_domain_product("Молоко", store=store, lookup=lookup)
    result = import_domain_products(
        _rows((2, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.linked == 1
    assert len(store.list_visible()) == 1
    assert store.list_visible()[0].catalog_code == "2311"


def test_import_later_row_links_product_from_earlier_row() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    result = import_domain_products(
        _rows((2, "Молоко", ""), (3, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.linked == 1
    assert result.unchanged == 0
    assert len(store.list_visible()) == 1
    assert store.list_visible()[0].catalog_code == "2311"


def test_import_name_match_is_case_sensitive() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    result = import_domain_products(
        _rows((2, "Кола", ""), (3, "кола", "")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 2
    names = {product.name for product in store.list_visible()}
    assert names == {"Кола", "кола"}


def test_import_links_archived_catalog_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="9001", name="Старое", archived=True),))
    result = import_domain_products(
        _rows((2, "Старое", "9001")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.linked == 1
    assert store.list_visible()[0].catalog_code == "9001"


def test_import_hidden_holder_blocks_create() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    holder = create_domain_product("Скрытый", store=store, lookup=lookup)
    link_domain_product(holder.domain_product_id, "2311", store=store, lookup=lookup)
    hide_domain_product(holder.domain_product_id, store=store)
    result = import_domain_products(
        _rows((2, "Новый", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.linked == 0
    assert len(result.failures) == 1
    assert result.failures[0].message == CARD_TAKEN_TEXT
    assert store.get_by_catalog_code("2311") is not None
    assert all(product.name != "Новый" for product in store.list_visible())


def test_import_hidden_same_name_creates_new() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    holder = create_domain_product("Молоко", store=store, lookup=lookup)
    hide_domain_product(holder.domain_product_id, store=store)
    result = import_domain_products(
        _rows((2, "Молоко", "")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.failures == ()
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].name == "Молоко"
    assert visible[0].domain_product_id != holder.domain_product_id


def test_import_skips_blank_rows_in_counters() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    result = import_domain_products(
        _rows((2, "  ", "  "), (3, "Молоко", "")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.unchanged == 0
    assert result.failures == ()


def test_import_missing_code_does_not_create() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    result = import_domain_products(
        _rows((2, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.failures[0].message == CODE_MISSING_TEXT
    assert store.list_visible() == ()


def test_import_taken_code_does_not_create() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    holder = create_domain_product("Первый", store=store, lookup=lookup)
    link_domain_product(holder.domain_product_id, "2311", store=store, lookup=lookup)
    result = import_domain_products(
        _rows((2, "Второй", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.failures[0].message == CARD_TAKEN_TEXT
    assert len(store.list_visible()) == 1


def test_import_other_card_does_not_relink() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="2311", name="A", archived=False),
            CatalogProduct(code="2400", name="B", archived=False),
        )
    )
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    result = import_domain_products(
        _rows((2, "Молоко", "2400")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.linked == 0
    assert result.failures[0].message == OTHER_CARD_TEXT
    assert store.get(product.domain_product_id).catalog_code == "2311"


def test_import_ambiguous_name_writes_nothing() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    create_domain_product("Молоко", store=store, lookup=lookup)
    create_domain_product("Молоко", store=store, lookup=lookup)
    result = import_domain_products(
        _rows((2, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.linked == 0
    assert result.failures[0].message == AMBIGUOUS_NAME_TEXT
    assert all(product.catalog_code is None for product in store.list_visible())


def test_import_empty_name_with_code_fails() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    result = import_domain_products(
        _rows((2, "  ", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 0
    assert result.failures[0].message == EMPTY_NAME_TEXT
    assert store.list_visible() == ()


def test_import_link_race_keeps_created_without_code() -> None:
    store = FakeDomainProductStore()
    store.fail_catalog_code_once = "2311"
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    result = import_domain_products(
        _rows((2, "Молоко", "2311")),
        store=store,
        lookup=lookup,
    )
    assert result.created == 1
    assert result.linked == 0
    assert len(result.failures) == 1
    assert result.failures[0].message == CARD_TAKEN_TEXT
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].catalog_code is None
