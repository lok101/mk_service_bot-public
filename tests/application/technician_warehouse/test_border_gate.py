from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore
from tests.application.technician_warehouse_import.fakes import (
    _CATALOG_RESOLVER,
    FakeTransferReader,
    _repository,
)

from src.application.product_identity.border_registration import (
    MemoryBorderRegistrationStore,
    ignore_border_code,
)
from src.application.product_identity.commands import (
    add_domain_product_link,
    create_domain_product,
)
from src.application.product_identity.models import CatalogProduct, ProductUnit
from src.application.technician_warehouse.errors import TechnicianWarehouseImportBlocked
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
    format_unregistered_border_blocker,
)
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ExternalWarehouseMoveLine,
)
from src.domain.ids import TechnicianId
from src.infrastructure.composition.adapters.border_product_gate import ProductIdentityBorderGate

_TECHNICIAN_ID = TechnicianId("tech-1")
_ANCHOR = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_AFTER = _ANCHOR + timedelta(days=1)


def _move(
    code: str,
    *,
    doc: str = "doc-1",
    moment: datetime = _T1,
    product_name: str | None = None,
) -> ExternalWarehouseMove:
    return ExternalWarehouseMove(
        document_id=doc,
        source_store_code="main",
        target_store_code="tech-1",
        moment=moment,
        updated_at=moment,
        lines=(
            ExternalWarehouseMoveLine(
                product_code=code,
                product_name=code if product_name is None else product_name,
                quantity=Decimal("1"),
            ),
        ),
    )


def _importer(
    moves: tuple[ExternalWarehouseMove, ...],
    *,
    products: FakeDomainProductStore,
    border: MemoryBorderRegistrationStore,
) -> ImportTechnicianWarehouseTransfers:
    return ImportTechnicianWarehouseTransfers(
        reader=FakeTransferReader(moves=moves),
        catalog_base_quantity_resolver=_CATALOG_RESOLVER,
        executor=TechnicianWarehouseExecutor(repository=_repository()),
        supply_store_codes=("main",),
        lookback_days=60,
        border_gate=ProductIdentityBorderGate(products=products, border=border),
    )


def test_unregistered_in_window_blocks_import() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    uc = _importer(
        (_move("raw-new", product_name="Сырьё Новый"),),
        products=products,
        border=border,
    )
    with pytest.raises(TechnicianWarehouseImportBlocked, match="unregistered") as exc_info:
        asyncio.run(uc.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    blocked = exc_info.value
    assert border.list_pending()[0].ms_code == "raw-new"
    assert blocked.technician_id == "tech-1"
    assert blocked.unregistered_products == (("raw-new", "Сырьё Новый"),)
    assert str(blocked) == format_unregistered_border_blocker(
        products=(("raw-new", "Сырьё Новый"),),
    )


def test_unregistered_blocker_empty_name_uses_code_only() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    uc = _importer(
        (_move("raw-empty", product_name=""),),
        products=products,
        border=border,
    )
    with pytest.raises(TechnicianWarehouseImportBlocked) as exc_info:
        asyncio.run(uc.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert exc_info.value.unregistered_products == (("raw-empty", ""),)
    assert "raw-empty" in str(exc_info.value)
    assert "—" not in str(exc_info.value)


def test_format_unregistered_border_blocker_samples_at_most_five() -> None:
    products = tuple((f"c{i}", f"Name {i}") for i in range(7))
    message = format_unregistered_border_blocker(products=products)
    assert "count=7" in message
    assert "c0 — Name 0" in message
    assert "c4 — Name 4" in message
    assert "c5" not in message
    assert "и ещё 2" in message


def test_ignored_does_not_block_and_skips_conversion() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    ignore_border_code("raw-skip", products=products, border=border)
    uc = _importer((_move("raw-skip"),), products=products, border=border)
    result = asyncio.run(uc.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    # Truncate-all still observes empty lines (reimport after catalog/un-ignore).
    assert result.imported == 1
    assert result.truncated_non_domain == 1


def test_linked_ingredient_imports() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="coffee-rich", name="Coffee", archived=False),))
    product = create_domain_product(
        "Кофе",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(
        product.domain_product_id,
        "coffee-rich",
        store=products,
        lookup=lookup,
    )
    uc = _importer((_move("coffee-rich"),), products=products, border=border)
    result = asyncio.run(uc.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.imported == 1
    assert result.skipped_unresolved == 0


def test_code_only_outside_window_moves_does_not_block() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="coffee-rich", name="Coffee", archived=False),))
    product = create_domain_product(
        "Кофе",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(
        product.domain_product_id,
        "coffee-rich",
        store=products,
        lookup=lookup,
    )
    uc = _importer(
        (
            _move("coffee-rich", doc="in-window"),
            _move("raw-future", doc="after-window", moment=_AFTER),
        ),
        products=products,
        border=border,
    )
    result = asyncio.run(uc.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    assert result.imported == 1
    assert border.list_pending() == ()
