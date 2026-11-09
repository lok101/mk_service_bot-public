from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.form_inventory_policy import (
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    seed_coffee_ingredient_policies,
)
from src.application.product_identity.models import DomainProduct
from src.domain.form_tokens import verify_technician_warehouse_inventory_token
from src.domain.ids import TechnicianId
from src.domain.product_catalog import ProductUnit
from src.infrastructure.field_forms import (
    TechnicianWarehouseInventoryFieldFormLinkProvider,
    technician_warehouse_field_form_issue_enabled,
)


class _MemoryProducts:
    def __init__(self, products: tuple[DomainProduct, ...] = ()) -> None:
        self._products = products

    def list_visible(self) -> tuple[DomainProduct, ...]:
        return tuple(p for p in self._products if not p.hidden)

    def get_by_number(self, number: str) -> DomainProduct | None:
        for product in self._products:
            if product.number == number:
                return product
        return None

    def get(self, domain_product_id: str) -> DomainProduct | None:
        del domain_product_id
        return None

    def get_by_catalog_code(self, catalog_code: str) -> DomainProduct | None:
        del catalog_code
        return None

    def insert(self, product: DomainProduct) -> None:
        del product

    def save(self, product: DomainProduct) -> None:
        del product

    def numbers(self) -> tuple[str, ...]:
        return tuple(p.number for p in self._products)


_SECRET = "warehouse-link-secret"
_TECH = TechnicianId("t1")
_CLOCK = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
_BASE = "https://bot.example.com"


def _ingredient(number: str, *, ready: bool = True) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=f"Name {number}",
        catalog_code="ms-1",
        hidden=False,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM if ready else None,
        pack_size=Decimal("1000") if ready else None,
    )


def _policies(*numbers: str) -> MemoryFormInventoryPolicyStore:
    store = MemoryFormInventoryPolicyStore()
    for number in numbers:
        seed_coffee_ingredient_policies(
            store,
            domain_number=number,
            loading=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
                radio_n=5,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("99"),
            ),
        )
    return store


def test_my_stock_field_form_url_on_cutover() -> None:
    """happy: cutover issue → FieldForm URL with warehouse token."""
    assert technician_warehouse_field_form_issue_enabled(
        field_forms_public_base_url=_BASE,
        technician_warehouse_inventory_form_url="",
    )
    provider = TechnicianWarehouseInventoryFieldFormLinkProvider(
        products=_MemoryProducts((_ingredient("d-1"),)),
        policies=_policies("d-1"),
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    link = provider.create_link(_TECH)
    assert link.url.startswith(f"{_BASE}/forms/technician-warehouse-inventory?token=")
    token = link.url.split("token=", 1)[1]
    payload = verify_technician_warehouse_inventory_token(token, _SECRET)
    assert payload.technician_id == _TECH


def test_my_stock_unconfigured_without_channels() -> None:
    """edge: no FieldForm when base URL empty even if Google URL empty."""
    assert not technician_warehouse_field_form_issue_enabled(
        field_forms_public_base_url="",
        technician_warehouse_inventory_form_url="",
    )
    assert not technician_warehouse_field_form_issue_enabled(
        field_forms_public_base_url=_BASE,
        technician_warehouse_inventory_form_url="https://forms.gle/warehouse",
    )


def test_issue_fails_without_policy_or_pack() -> None:
    """error: missing pack/policy → fail-fast on issue."""
    provider = TechnicianWarehouseInventoryFieldFormLinkProvider(
        products=_MemoryProducts((_ingredient("d-1", ready=False),)),
        policies=_policies(),
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    with pytest.raises(ValueError, match="упаковки или политики"):
        provider.create_link(_TECH)
