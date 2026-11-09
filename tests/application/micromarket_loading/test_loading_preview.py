from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.micromarket_loading import GetMicromarketLoadingPreview
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.product_identity import create_domain_product
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)

_UPDATED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def test_loading_preview_rows_stock_target_price() -> None:
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine("2311", 5, Decimal("189.00"), True, 0),
                MicromarketPlanogramLine("9999", 3, Decimal("50.00"), False, 1),
            ),
            updated_at=_UPDATED_AT,
        ),
    )
    stocks = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("2")},
        inventory_id="inv-1",
    )
    stocks.save(stock)
    uc = GetMicromarketLoadingPreview(
        planogram_store=planograms,
        stock_store=stocks,
        catalog_names={"2311": "Салат"},
    )
    preview = uc.execute("701")
    assert len(preview.rows) == 1
    row = preview.rows[0]
    assert row.product_code == "2311"
    assert row.stock_qty == Decimal("2")
    assert row.target_qty == 5
    assert row.price_rub == Decimal("189.00")
    assert not hasattr(row, "to_load") or getattr(row, "to_load", None) is None


def test_loading_preview_uses_domain_number_and_name_without_catalog() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    planograms = InMemoryMicromarketPlanogramStore()
    planograms.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=5,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=_UPDATED_AT,
        )
    )
    stocks = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_UPDATED_AT,
        quantities={product.number: Decimal("2")},
        inventory_id="inv-1",
    )
    stocks.save(stock)
    preview = GetMicromarketLoadingPreview(
        planogram_store=planograms,
        stock_store=stocks,
        catalog_names={},
        products=store,
    ).execute("701")
    assert len(preview.rows) == 1
    assert preview.rows[0].product_code == product.number
    assert preview.rows[0].name == "Молоко"
    assert preview.rows[0].stock_qty == Decimal("2")


def test_loading_preview_empty_planogram() -> None:
    planograms = InMemoryMicromarketPlanogramStore()
    stocks = InMemoryMicromarketDeviceStockStore()
    uc = GetMicromarketLoadingPreview(
        planogram_store=planograms,
        stock_store=stocks,
        catalog_names={},
    )
    preview = uc.execute("701")
    assert preview.rows == ()
