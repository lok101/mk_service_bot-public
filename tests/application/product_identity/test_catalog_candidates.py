from __future__ import annotations

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.catalog_candidates import (
    CatalogCandidate,
    CatalogCandidatesImportFailure,
    CatalogCandidatesImportResult,
    import_catalog_candidates,
    list_catalog_candidates,
)
from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
    link_domain_product,
)
from src.application.product_identity.models import (
    CARD_TAKEN_TEXT,
    CODE_MISSING_TEXT,
    NUMBER_NOT_ISSUED_TEXT,
    CatalogProduct,
)


def test_list_returns_free_codes_in_snapshot_order() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="A", name="Первый", archived=False),
            CatalogProduct(code="B", name="Второй", archived=False),
            CatalogProduct(code="C", name="Третий", archived=True),
        )
    )
    create_domain_product("Занятый", store=store, lookup=lookup)
    link_domain_product(
        store.list_visible()[0].domain_product_id,
        "B",
        store=store,
        lookup=lookup,
    )

    candidates = list_catalog_candidates(store=store, lookup=lookup)

    assert candidates == (
        CatalogCandidate(code="A", name="Первый", archived=False),
        CatalogCandidate(code="C", name="Третий", archived=True),
    )


def test_list_excludes_code_held_by_hidden_product() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="H1", name="Скрытый", archived=False),))
    product = create_domain_product("Держатель", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "H1", store=store, lookup=lookup)
    hide_domain_product(product.domain_product_id, store=store)

    assert list_catalog_candidates(store=store, lookup=lookup) == ()


def test_import_creates_and_links_free_code_with_snapshot_name() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="  Молоко МС  ", archived=False),))

    result = import_catalog_candidates(("2311",), store=store, lookup=lookup)

    assert result == CatalogCandidatesImportResult(created=1, unchanged=0, failures=())
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].name == "Молоко МС"
    assert visible[0].catalog_code == "2311"


def test_import_partial_success_across_codes() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="OK", name="Свободный", archived=False),
            CatalogProduct(code="TAKEN", name="Занятый", archived=False),
        )
    )
    existing = create_domain_product("Уже есть", store=store, lookup=lookup)
    link_domain_product(existing.domain_product_id, "TAKEN", store=store, lookup=lookup)

    result = import_catalog_candidates(
        ("OK", "TAKEN", "GONE"),
        store=store,
        lookup=lookup,
    )

    assert result.created == 1
    assert result.unchanged == 1
    assert result.failures == (
        CatalogCandidatesImportFailure(code="GONE", message=CODE_MISSING_TEXT),
    )
    assert store.get_by_catalog_code("OK") is not None
    assert store.get_by_catalog_code("TAKEN") is not None


def test_import_taken_including_hidden_counts_unchanged() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="H1", name="Карточка", archived=False),))
    product = create_domain_product("Держатель", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "H1", store=store, lookup=lookup)
    hide_domain_product(product.domain_product_id, store=store)
    before = store.writes

    result = import_catalog_candidates(("H1",), store=store, lookup=lookup)

    assert result == CatalogCandidatesImportResult(created=0, unchanged=1, failures=())
    assert store.writes == before


def test_import_archived_free_code_succeeds() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="9001", name="Архив", archived=True),))

    result = import_catalog_candidates(("9001",), store=store, lookup=lookup)

    assert result.created == 1
    assert store.list_visible()[0].catalog_code == "9001"
    assert store.list_visible()[0].name == "Архив"


def test_import_same_name_as_visible_still_creates() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="NEW", name="Молоко", archived=False),))
    create_domain_product("Молоко", store=store, lookup=lookup)

    result = import_catalog_candidates(("NEW",), store=store, lookup=lookup)

    assert result.created == 1
    visible = store.list_visible()
    assert len(visible) == 2
    assert {p.catalog_code for p in visible} == {None, "NEW"}


def test_import_repeat_after_success_is_unchanged() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    import_catalog_candidates(("2311",), store=store, lookup=lookup)

    again = import_catalog_candidates(("2311",), store=store, lookup=lookup)

    assert again == CatalogCandidatesImportResult(created=0, unchanged=1, failures=())
    assert len(store.list_visible()) == 1


def test_import_missing_code_fails_with_code_missing_text() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())

    result = import_catalog_candidates(("NOPE",), store=store, lookup=lookup)

    assert result == CatalogCandidatesImportResult(
        created=0,
        unchanged=0,
        failures=(CatalogCandidatesImportFailure(code="NOPE", message=CODE_MISSING_TEXT),),
    )
    assert store.list_visible() == ()


def test_import_link_race_leaves_product_without_code() -> None:
    store = FakeDomainProductStore()
    store.fail_catalog_code_once = "RACE"
    lookup = FakeCatalogLookup((CatalogProduct(code="RACE", name="Гонка", archived=False),))

    result = import_catalog_candidates(("RACE",), store=store, lookup=lookup)

    assert result.created == 0
    assert result.unchanged == 0
    assert len(result.failures) == 1
    assert result.failures[0].code == "RACE"
    assert result.failures[0].message == CARD_TAKEN_TEXT
    visible = store.list_visible()
    assert len(visible) == 1
    assert visible[0].name == "Гонка"
    assert visible[0].catalog_code is None


def test_import_number_not_issued_keeps_earlier_success() -> None:
    store = FakeDomainProductStore()
    colliding = FakeCatalogLookup(
        (
            CatalogProduct(code="OK", name="Ок", archived=False),
            CatalogProduct(code="FAIL", name="Провал", archived=False),
        )
    )
    original_collides = colliding.number_collides
    call_count = {"n": 0}

    def _collides_after_first_success(number: str) -> bool:
        call_count["n"] += 1
        if call_count["n"] > 1 and store.get_by_catalog_code("OK") is not None:
            return True
        return original_collides(number)

    colliding.number_collides = _collides_after_first_success  # type: ignore[method-assign]

    result = import_catalog_candidates(("OK", "FAIL"), store=store, lookup=colliding)

    assert result.created == 1
    assert result.failures == (
        CatalogCandidatesImportFailure(code="FAIL", message=NUMBER_NOT_ISSUED_TEXT),
    )
    assert store.get_by_catalog_code("OK") is not None
    assert store.get_by_catalog_code("FAIL") is None
