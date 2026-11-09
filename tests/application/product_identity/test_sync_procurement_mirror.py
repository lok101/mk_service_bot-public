from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.product_identity.models import DomainProduct
from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementMirror,
    ProcurementSupplySnapshot,
)
from src.application.product_identity.sync_procurement_mirror import (
    ProcurementMirrorSyncStats,
    SyncProcurementMirror,
)
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_OLD = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


@dataclass
class _FakeFetcher:
    outcomes: dict[str, ProcurementSupplySnapshot | ProcurementFetchFailed | Exception]

    def fetch(self, catalog_code: str) -> ProcurementSupplySnapshot | ProcurementFetchFailed:
        outcome = self.outcomes[catalog_code]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _product(
    *,
    pid: str,
    number: str,
    code: str | None,
    hidden: bool = False,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=pid,
        number=number,
        name=f"Name {number}",
        catalog_code=code,
        hidden=hidden,
    )


def _sync(
    *,
    enabled: bool = True,
    products: FakeDomainProductStore,
    mirrors: MemoryProcurementMirrorStore,
    fetcher: _FakeFetcher,
) -> SyncProcurementMirror:
    return SyncProcurementMirror(
        enabled=enabled,
        products=products,
        mirrors=mirrors,
        fetcher=fetcher,
        clock=lambda: _NOW,
        supply_concurrency=1,
    )


def test_sync_all_upserts_supplier_price_and_synced_at() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311"))
    mirrors = MemoryProcurementMirrorStore()
    fetcher = _FakeFetcher(
        {
            "2311": ProcurementSupplySnapshot(
                catalog_code="2311",
                supplier_id="agent-1",
                supplier_name="ООО Поставщик",
                last_buy_price=Decimal("12.50"),
                supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
                package_quantity=Decimal("6"),
                supplier_product_name="Салат у поставщика",
            )
        }
    )
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_all()
    assert stats == ProcurementMirrorSyncStats(
        requested=1, upserted=1, empty_supply=0, http_failed=0, pruned=0
    )
    row = mirrors.get("2311")
    assert row is not None
    assert row.supplier_name == "ООО Поставщик"
    assert row.last_buy_price == Decimal("12.50")
    assert row.synced_at == _NOW
    assert row.package_quantity == Decimal("6")
    assert row.supplier_product_name == "Салат у поставщика"


def test_sync_all_empty_supply_upserts_none_not_zero() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311"))
    mirrors = MemoryProcurementMirrorStore()
    fetcher = _FakeFetcher(
        {
            "2311": ProcurementSupplySnapshot(
                catalog_code="2311",
                supplier_id=None,
                supplier_name=None,
                last_buy_price=None,
                supply_moment=None,
            )
        }
    )
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_all()
    assert stats.empty_supply == 1
    assert stats.upserted == 1
    row = mirrors.get("2311")
    assert row is not None
    assert row.last_buy_price is None
    assert row.supplier_id is None


def test_sync_all_http_fail_preserves_previous_row() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311"))
    mirrors = MemoryProcurementMirrorStore()
    previous = ProcurementMirror(
        catalog_code="2311",
        supplier_id="old",
        supplier_name="Старый",
        last_buy_price=Decimal("9.00"),
        supply_moment=_OLD,
        synced_at=_OLD,
    )
    mirrors.upsert(previous)
    fetcher = _FakeFetcher({"2311": ProcurementFetchFailed(catalog_code="2311")})
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_all()
    assert stats.http_failed == 1
    assert stats.upserted == 0
    assert mirrors.get("2311") == previous


def test_sync_all_includes_hidden_products() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311", hidden=True))
    mirrors = MemoryProcurementMirrorStore()
    fetcher = _FakeFetcher(
        {
            "2311": ProcurementSupplySnapshot(
                catalog_code="2311",
                supplier_id=None,
                supplier_name=None,
                last_buy_price=Decimal("1.00"),
                supply_moment=_OLD,
            )
        }
    )
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_all()
    assert stats.requested == 1
    assert mirrors.get("2311") is not None


def test_sync_all_prunes_codes_no_longer_linked() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311"))
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="9999",
            supplier_id=None,
            supplier_name=None,
            last_buy_price=None,
            supply_moment=None,
            synced_at=_OLD,
        )
    )
    fetcher = _FakeFetcher(
        {
            "2311": ProcurementSupplySnapshot(
                catalog_code="2311",
                supplier_id=None,
                supplier_name=None,
                last_buy_price=None,
                supply_moment=None,
            )
        }
    )
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_all()
    assert stats.pruned == 1
    assert mirrors.get("9999") is None
    assert mirrors.get("2311") is not None


def test_sync_codes_flag_off_is_noop() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(pid="a", number="d-1", code="2311"))
    mirrors = MemoryProcurementMirrorStore()
    fetcher = _FakeFetcher({})
    stats = _sync(enabled=False, products=products, mirrors=mirrors, fetcher=fetcher).sync_codes(
        "2311"
    )
    assert stats == ProcurementMirrorSyncStats(
        requested=0, upserted=0, empty_supply=0, http_failed=0, pruned=0
    )
    assert mirrors.get("2311") is None


def test_sync_codes_unlinked_code_deletes_without_http() -> None:
    products = FakeDomainProductStore()
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="2311",
            supplier_id="x",
            supplier_name="Y",
            last_buy_price=Decimal("3"),
            supply_moment=_OLD,
            synced_at=_OLD,
        )
    )
    fetcher = _FakeFetcher({})
    stats = _sync(products=products, mirrors=mirrors, fetcher=fetcher).sync_codes("2311")
    assert stats.pruned == 1
    assert stats.requested == 0
    assert mirrors.get("2311") is None


def test_memory_procurement_mirror_codes_lists_keys() -> None:
    store = MemoryProcurementMirrorStore()
    store.upsert(
        ProcurementMirror(
            catalog_code="2311",
            supplier_id=None,
            supplier_name=None,
            last_buy_price=None,
            supply_moment=None,
            synced_at=_NOW,
        )
    )
    assert store.codes() == ("2311",)
