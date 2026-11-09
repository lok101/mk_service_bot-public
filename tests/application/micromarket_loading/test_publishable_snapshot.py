from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.publishable_snapshot import (
    build_publishable_snapshot,
)
from src.application.product_identity import DomainProduct, create_domain_product
from src.domain.micromarket_loading import MicromarketDeviceStock

_AT = datetime(2026, 9, 28, tzinfo=UTC)


def _product(
    domain_product_id: str,
    name: str,
    catalog_code: str | None,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=f"n-{domain_product_id}",
        name=name,
        catalog_code=catalog_code,
        hidden=False,
    )


def _line(
    *,
    product_code: str,
    domain_product_id: str | None,
    price: Decimal,
    sort_order: int,
    active: bool = True,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=product_code,
        target_qty=1,
        price_rub=price,
        active=active,
        sort_order=sort_order,
        kit_group_id=6348,
        domain_product_id=domain_product_id,
    )


def _doc(*lines: MicromarketPlanogramLine) -> MicromarketPlanogram:
    return MicromarketPlanogram(
        machine_code="701",
        lines=lines,
        updated_at=_AT,
    )


def test_publishable_snapshot_uses_domain_number_without_catalog() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    doc = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(
                product_code="",
                domain_product_id=product.domain_product_id,
                price=Decimal("15"),
                sort_order=0,
            ),
        ),
        updated_at=_AT,
    )
    snapshot = build_publishable_snapshot(doc, store)
    assert [line.product_code for line in snapshot.lines] == [product.number]
    assert snapshot.skipped_names == ()


def test_publishable_snapshot_skips_product_code_only_line() -> None:
    doc = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(
                product_code="2311",
                domain_product_id=None,
                price=Decimal("10"),
                sort_order=0,
            ),
        ),
        updated_at=_AT,
    )
    snapshot = build_publishable_snapshot(doc, FakeDomainProductStore())
    assert snapshot.lines == ()
    assert snapshot.skipped_names == ("2311",)


def test_publishable_snapshot_keeps_factual_zero_as_disabled() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={product.number: Decimal("0")},
        inventory_id="inv-1",
    )
    doc = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(
                product_code="",
                domain_product_id=product.domain_product_id,
                price=Decimal("15"),
                sort_order=0,
            ),
        ),
        updated_at=_AT,
    )
    snapshot = build_publishable_snapshot(doc, store, stock=stock)
    assert [line.product_code for line in snapshot.lines] == [product.number]
    assert [entry.disabled for entry in snapshot.lines] == [True]


def test_publishable_snapshot_includes_domain_number_even_with_catalog() -> None:
    products = FakeDomainProductStore()
    products.insert(_product("prod-1", "Кефир", "2311"))
    products.insert(_product("prod-2", "Сок", "2400"))
    doc = _doc(
        _line(product_code="", domain_product_id="prod-1", price=Decimal("15"), sort_order=0),
        _line(product_code="", domain_product_id="prod-2", price=Decimal("20"), sort_order=1),
        _line(
            product_code="9999",
            domain_product_id=None,
            price=Decimal("5"),
            sort_order=2,
            active=False,
        ),
    )
    snapshot = build_publishable_snapshot(doc, products)
    assert [line.product_code for line in snapshot.lines] == ["n-prod-1", "n-prod-2"]
    assert snapshot.skipped_names == ()


def test_publishable_snapshot_skips_missing_domain_product() -> None:
    doc = _doc(
        _line(product_code="", domain_product_id="missing", price=Decimal("10"), sort_order=0),
    )
    snapshot = build_publishable_snapshot(doc, FakeDomainProductStore())
    assert snapshot.lines == ()
    assert snapshot.skipped_names == ("Товар не найден",)


def _stock_with_factuals(machine_code: str, pairs: dict[str, Decimal]) -> MicromarketDeviceStock:
    stock = MicromarketDeviceStock(machine_code=machine_code)
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
        quantities=pairs,
        inventory_id="seed-snap",
        partial=True,
    )
    return stock


def test_publishable_snapshot_marks_last_factual_zero_disabled() -> None:
    products = FakeDomainProductStore()
    products.insert(_product("prod-1", "A", None))
    products.insert(_product("prod-2", "B", None))
    doc = _doc(
        _line(product_code="", domain_product_id="prod-1", price=Decimal("10"), sort_order=0),
        _line(product_code="", domain_product_id="prod-2", price=Decimal("20"), sort_order=1),
    )
    stock = _stock_with_factuals("701", {"n-prod-1": Decimal("0"), "n-prod-2": Decimal("3")})
    snapshot = build_publishable_snapshot(doc, products, stock=stock)
    assert [entry.product_code for entry in snapshot.lines] == ["n-prod-1", "n-prod-2"]
    assert [entry.disabled for entry in snapshot.lines] == [True, False]


def test_publishable_snapshot_keeps_pending_exit_line_without_factual_zero() -> None:
    products = FakeDomainProductStore()
    products.insert(_product("prod-1", "A", None))
    products.insert(_product("prod-2", "B", None))
    doc = _doc(
        MicromarketPlanogramLine(
            product_code="",
            target_qty=1,
            price_rub=Decimal("10"),
            active=True,
            sort_order=0,
            kit_group_id=6348,
            pending_exit=True,
            domain_product_id="prod-1",
        ),
        _line(product_code="", domain_product_id="prod-2", price=Decimal("20"), sort_order=1),
    )
    stock = _stock_with_factuals("701", {"n-prod-1": Decimal("2"), "n-prod-2": Decimal("1")})
    snapshot = build_publishable_snapshot(doc, products, stock=stock)
    assert [line.product_code for line in snapshot.lines] == ["n-prod-1", "n-prod-2"]


def test_publishable_snapshot_keeps_code_when_last_factual_missing_or_nonzero() -> None:
    """Omit / virtual / нет last_factual: номер остаётся на витрине (приёмка 3)."""
    products = FakeDomainProductStore()
    products.insert(_product("prod-1", "A", None))
    doc = _doc(
        _line(product_code="", domain_product_id="prod-1", price=Decimal("10"), sort_order=0),
    )
    missing = MicromarketDeviceStock(machine_code="701")
    assert missing.last_factual_qty("n-prod-1") is None
    snap_missing = build_publishable_snapshot(doc, products, stock=missing)
    assert [line.product_code for line in snap_missing.lines] == ["n-prod-1"]

    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
        quantities={"n-prod-1": Decimal("5")},
        inventory_id="seed-omit",
        partial=True,
    )
    stock.apply_sale_deduct(
        sale_source_id="s1",
        product_code="n-prod-1",
        qty=Decimal("5"),
        occurred_at=datetime(2026, 10, 1, 1, tzinfo=UTC),
    )
    assert stock.qty("n-prod-1") == Decimal("0")
    assert stock.last_factual_qty("n-prod-1") == Decimal("5")
    snapshot = build_publishable_snapshot(doc, products, stock=stock)
    assert [line.product_code for line in snapshot.lines] == ["n-prod-1"]
    assert [entry.disabled for entry in snapshot.lines] == [False]
    assert [entry.disabled for entry in snap_missing.lines] == [False]


def test_publishable_snapshot_without_stock_keeps_active_domain_filter() -> None:
    products = FakeDomainProductStore()
    products.insert(_product("prod-1", "A", None))
    doc = _doc(
        _line(product_code="", domain_product_id="prod-1", price=Decimal("10"), sort_order=0),
        _line(
            product_code="",
            domain_product_id="prod-1",
            price=Decimal("5"),
            sort_order=1,
            active=False,
        ),
    )
    snapshot = build_publishable_snapshot(doc, products)
    assert [line.product_code for line in snapshot.lines] == ["n-prod-1"]
