from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.sync_warehouse_stock import (
    SyncMicromarketWarehouseStock,
    collect_planogram_catalog_codes,
)
from src.application.product_identity.models import DomainProduct
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_WAREHOUSE = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_AT = datetime(2026, 10, 27, 7, 0, tzinfo=UTC)


class _Fetcher:
    def __init__(self, qty: Mapping[str, Decimal]) -> None:
        self._qty = dict(qty)
        self.calls: list[tuple[str, ...]] = []

    def fetch_qty_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Mapping[str, Decimal]:
        self.calls.append(tuple(catalog_codes))
        return {code: self._qty.get(code, Decimal("0")) for code in catalog_codes}


def test_collect_planogram_catalog_codes_union() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="m1",
            lines=(
                MicromarketPlanogramLine(
                    product_code="A",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                ),
                MicromarketPlanogramLine(
                    product_code="B",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=1,
                ),
            ),
            updated_at=_AT,
        ),
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code="m2",
            lines=(
                MicromarketPlanogramLine(
                    product_code="B",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                ),
            ),
            updated_at=_AT,
        ),
    )
    assert collect_planogram_catalog_codes(planograms=store, products=None) == ("A", "B")


def test_collect_planogram_catalog_codes_via_domain_product_id() -> None:
    """edge: empty product_code + domain_product_id (prod planogram shape) → MS catalog."""
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="pid-1",
            number="d-2",
            name="BonaAqua",
            catalog_code="16161616003392",
            hidden=False,
        ),
    )
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="704",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=6,
                    price_rub=Decimal("50"),
                    active=True,
                    sort_order=0,
                    domain_product_id="pid-1",
                ),
            ),
            updated_at=_AT,
        ),
    )
    assert collect_planogram_catalog_codes(planograms=store, products=products) == (
        "16161616003392",
    )


def test_collect_planogram_catalog_codes_falls_back_to_line_product_code() -> None:
    """edge: domain product without catalog_code — MS code only on line.product_code."""
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="pid-1",
            number="d-2",
            name="BonaAqua",
            catalog_code=None,
            hidden=False,
        ),
    )
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="704",
            lines=(
                MicromarketPlanogramLine(
                    product_code="16161616003392",
                    target_qty=6,
                    price_rub=Decimal("50"),
                    active=True,
                    sort_order=0,
                    domain_product_id="pid-1",
                ),
            ),
            updated_at=_AT,
        ),
    )
    assert collect_planogram_catalog_codes(planograms=store, products=products) == (
        "16161616003392",
    )


def test_sync_once_replaces_snapshot() -> None:
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(
        MicromarketPlanogram(
            machine_code="m1",
            lines=(
                MicromarketPlanogramLine(
                    product_code="SKU-1",
                    target_qty=2,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                ),
            ),
            updated_at=_AT,
        ),
    )
    snapshots = InMemoryMicromarketWarehouseStockSnapshotStore()
    fetcher = _Fetcher({"SKU-1": Decimal("17")})
    SyncMicromarketWarehouseStock(
        snapshot_store=snapshots,
        planograms=planograms,
        products=None,
        warehouse_id=_WAREHOUSE,
        fetcher=fetcher,
    ).sync_once(now=_AT)
    got = snapshots.get()
    assert got is not None
    assert got.qty_by_catalog_code["SKU-1"] == Decimal("17")
    assert fetcher.calls == [("SKU-1",)]


def test_sync_once_empty_planogram_union_writes_empty_map() -> None:
    """edge: no planogram lines → empty qty map with refreshed_at; fetcher unused."""
    planograms = InMemoryMicromarketPlanogramStore()
    snapshots = InMemoryMicromarketWarehouseStockSnapshotStore()
    fetcher = _Fetcher({"SKU-1": Decimal("99")})
    SyncMicromarketWarehouseStock(
        snapshot_store=snapshots,
        planograms=planograms,
        products=None,
        warehouse_id=_WAREHOUSE,
        fetcher=fetcher,
    ).sync_once(now=_AT)
    got = snapshots.get()
    assert got is not None
    assert got.qty_by_catalog_code == {}
    assert got.refreshed_at == _AT
    assert fetcher.calls == []


def test_sync_once_keeps_prior_on_fetcher_error() -> None:
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(
        MicromarketPlanogram(
            machine_code="m1",
            lines=(
                MicromarketPlanogramLine(
                    product_code="SKU-1",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                ),
            ),
            updated_at=_AT,
        ),
    )
    snapshots = InMemoryMicromarketWarehouseStockSnapshotStore()
    SyncMicromarketWarehouseStock(
        snapshot_store=snapshots,
        planograms=planograms,
        products=None,
        warehouse_id=_WAREHOUSE,
        fetcher=_Fetcher({"SKU-1": Decimal("9")}),
    ).sync_once(now=_AT)

    class _Boom:
        def fetch_qty_by_catalog_codes(self, catalog_codes: Sequence[str]) -> Mapping[str, Decimal]:
            raise RuntimeError("ms down")

    with contextlib.suppress(RuntimeError):
        SyncMicromarketWarehouseStock(
            snapshot_store=snapshots,
            planograms=planograms,
            products=None,
            warehouse_id=_WAREHOUSE,
            fetcher=_Boom(),
        ).sync_once(now=_AT)
    got = snapshots.get()
    assert got is not None
    assert got.qty_by_catalog_code["SKU-1"] == Decimal("9")
