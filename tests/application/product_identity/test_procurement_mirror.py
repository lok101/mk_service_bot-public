from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal

from src.application.product_identity.models import DomainProduct
from src.application.product_identity.ports import (
    ProcurementAttributesFetcher,
    ProcurementMirrorStore,
)
from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementMirror,
    ProcurementSupplySnapshot,
)


def test_procurement_mirror_holds_supplier_price_and_moments() -> None:
    synced = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    supply = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
    mirror = ProcurementMirror(
        catalog_code="2311",
        supplier_id="agent-1",
        supplier_name="ООО Поставщик",
        last_buy_price=Decimal("12.50"),
        supply_moment=supply,
        synced_at=synced,
        package_quantity=Decimal("6"),
        supplier_product_name="Салат у поставщика",
    )
    assert mirror.catalog_code == "2311"
    assert mirror.supplier_id == "agent-1"
    assert mirror.supplier_name == "ООО Поставщик"
    assert mirror.last_buy_price == Decimal("12.50")
    assert mirror.supply_moment == supply
    assert mirror.synced_at == synced
    assert mirror.package_quantity == Decimal("6")
    assert mirror.supplier_product_name == "Салат у поставщика"


def test_procurement_mirror_empty_supply_uses_none_not_zero() -> None:
    synced = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    mirror = ProcurementMirror(
        catalog_code="2311",
        supplier_id=None,
        supplier_name=None,
        last_buy_price=None,
        supply_moment=None,
        synced_at=synced,
    )
    assert mirror.last_buy_price is None
    assert mirror.supplier_id is None
    assert mirror.supply_moment is None


def test_procurement_supply_snapshot_and_fetch_failed_are_distinct() -> None:
    snap = ProcurementSupplySnapshot(
        catalog_code="2311",
        supplier_id=None,
        supplier_name=None,
        last_buy_price=None,
        supply_moment=None,
    )
    failed = ProcurementFetchFailed(catalog_code="2311")
    assert snap.catalog_code == "2311"
    assert failed.catalog_code == "2311"
    assert type(snap) is not type(failed)


def test_domain_product_has_no_procurement_fields() -> None:
    names = {item.name for item in fields(DomainProduct)}
    assert "supplier_id" not in names
    assert "supplier_name" not in names
    assert "last_buy_price" not in names
    assert "supply_moment" not in names
    assert "synced_at" not in names
    assert "package_quantity" not in names
    assert "supplier_product_name" not in names


def test_procurement_mirror_store_protocol_declares_get_upsert_delete() -> None:
    assert callable(ProcurementMirrorStore.get)
    assert callable(ProcurementMirrorStore.upsert)
    assert callable(ProcurementMirrorStore.delete)


def test_procurement_attributes_fetcher_protocol_declares_fetch() -> None:
    assert callable(ProcurementAttributesFetcher.fetch)


def test_procurement_mirror_exported_from_package() -> None:
    from src.application import product_identity as pkg

    assert pkg.ProcurementMirror is ProcurementMirror
