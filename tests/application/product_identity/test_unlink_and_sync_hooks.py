from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore
from tests.application.product_identity.test_sync_procurement_mirror import _FakeFetcher

from src.application.product_identity.commands import (
    import_domain_products,
    link_domain_product,
    unlink_domain_product,
)
from src.application.product_identity.models import (
    CatalogProduct,
    DomainProduct,
    DomainProductImportRow,
)
from src.application.product_identity.procurement_mirror import (
    ProcurementMirror,
    ProcurementSupplySnapshot,
)
from src.application.product_identity.sync_procurement_mirror import SyncProcurementMirror
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _card(code: str) -> CatalogProduct:
    return CatalogProduct(code=code, name=f"Card {code}", archived=False)


def test_unlink_domain_product_clears_catalog_code() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code="2311",
            hidden=False,
        )
    )
    updated = unlink_domain_product("a", store=store)
    assert updated.catalog_code is None
    assert store.get("a") is not None
    assert store.get("a").catalog_code is None


def test_link_calls_sync_for_old_and_new_codes() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code="1111",
            hidden=False,
        )
    )
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="1111",
            supplier_id="old",
            supplier_name="Old",
            last_buy_price=Decimal("1"),
            supply_moment=_NOW,
            synced_at=_NOW,
        )
    )
    fetcher = _FakeFetcher(
        {
            "2222": ProcurementSupplySnapshot(
                catalog_code="2222",
                supplier_id="n",
                supplier_name="New",
                last_buy_price=Decimal("2.00"),
                supply_moment=_NOW,
            )
        }
    )
    sync = SyncProcurementMirror(
        enabled=True,
        products=store,
        mirrors=mirrors,
        fetcher=fetcher,
        clock=lambda: _NOW,
        supply_concurrency=1,
    )
    lookup = FakeCatalogLookup(cards=(_card("2222"),))
    link_domain_product(
        "a",
        "2222",
        store=store,
        lookup=lookup,
        procurement_sync=sync,
    )
    assert store.get("a").catalog_code == "2222"
    assert mirrors.get("2222") is not None
    assert mirrors.get("1111") is None


def test_unlink_with_sync_deletes_orphan_mirror() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code="2311",
            hidden=False,
        )
    )
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="2311",
            supplier_id="x",
            supplier_name="Y",
            last_buy_price=Decimal("3"),
            supply_moment=_NOW,
            synced_at=_NOW,
        )
    )
    sync = SyncProcurementMirror(
        enabled=True,
        products=store,
        mirrors=mirrors,
        fetcher=_FakeFetcher({}),
        clock=lambda: _NOW,
        supply_concurrency=1,
    )
    unlink_domain_product("a", store=store, procurement_sync=sync)
    assert store.get("a").catalog_code is None
    assert mirrors.get("2311") is None


def test_link_sync_failure_does_not_rollback_link() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code=None,
            hidden=False,
        )
    )
    mirrors = MemoryProcurementMirrorStore()

    class BoomFetcher:
        def fetch(self, catalog_code: str):
            raise RuntimeError("ms down")

    sync = SyncProcurementMirror(
        enabled=True,
        products=store,
        mirrors=mirrors,
        fetcher=BoomFetcher(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
        supply_concurrency=1,
    )
    lookup = FakeCatalogLookup(cards=(_card("2311"),))
    # sync_codes must swallow fetcher exceptions for best-effort OR link wraps try/except.
    # Требование спека: ошибка МС не откатывает связь.
    # Реализация: link ловит Exception вокруг sync_codes и не пробрасывает.
    updated = link_domain_product(
        "a",
        "2311",
        store=store,
        lookup=lookup,
        procurement_sync=sync,
    )
    assert updated.catalog_code == "2311"


def test_import_passes_sync_into_link() -> None:
    store = FakeDomainProductStore()
    mirrors = MemoryProcurementMirrorStore()
    fetcher = _FakeFetcher(
        {
            "2311": ProcurementSupplySnapshot(
                catalog_code="2311",
                supplier_id=None,
                supplier_name=None,
                last_buy_price=Decimal("4.00"),
                supply_moment=_NOW,
            )
        }
    )
    sync = SyncProcurementMirror(
        enabled=True,
        products=store,
        mirrors=mirrors,
        fetcher=fetcher,
        clock=lambda: _NOW,
        supply_concurrency=1,
    )
    lookup = FakeCatalogLookup(cards=(_card("2311"),))
    result = import_domain_products(
        (DomainProductImportRow(line_number=1, name="Новый", catalog_code="2311"),),
        store=store,
        lookup=lookup,
        procurement_sync=sync,
    )
    assert result.created == 1
    assert result.linked == 1
    assert mirrors.get("2311") is not None


def test_point_sync_flag_off_keeps_link_without_mirror_write() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="a",
            number="d-1",
            name="Товар",
            catalog_code=None,
            hidden=False,
        )
    )
    mirrors = MemoryProcurementMirrorStore()
    sync = SyncProcurementMirror(
        enabled=False,
        products=store,
        mirrors=mirrors,
        fetcher=_FakeFetcher({}),
        clock=lambda: _NOW,
        supply_concurrency=1,
    )
    lookup = FakeCatalogLookup(cards=(_card("2311"),))
    link_domain_product(
        "a",
        "2311",
        store=store,
        lookup=lookup,
        procurement_sync=sync,
    )
    assert store.get("a").catalog_code == "2311"
    assert mirrors.get("2311") is None
