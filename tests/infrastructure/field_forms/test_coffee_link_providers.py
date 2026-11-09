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
from src.domain.form_tokens import verify_coffee_form_token
from src.domain.ids import MachineId, TechnicianId
from src.domain.product_catalog import ProductUnit
from src.infrastructure.field_forms import (
    CoffeeFieldFormLoadingLinkProvider,
    CoffeeFieldFormRevisionLinkProvider,
    coffee_field_form_issue_enabled,
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


_SECRET = "link-secret"
_TECH = TechnicianId("t1")
_MACHINE = MachineId("m1")
_CLOCK = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
_BASE = "https://bot.example.com"


def _ingredient(number: str, *, hidden: bool = False, ready: bool = True) -> DomainProduct:
    return DomainProduct(
        domain_product_id=f"id-{number}",
        number=number,
        name=f"Name {number}",
        catalog_code="ms-1",
        hidden=hidden,
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
                max_qty=Decimal("20"),
                radio_n=5,
            ),
            revision=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("20"),
            ),
            warehouse=FormInventoryPolicyLine(
                domain_number=number,
                min_qty=Decimal("0"),
                max_qty=Decimal("20"),
            ),
        )
    return store


def test_workspace_loading_url_is_field_form() -> None:
    """happy: CreateLoadingForm / revision issue → FieldForm URL, not Google."""
    products = _MemoryProducts((_ingredient("d-1"), _ingredient("d-2", hidden=True)))
    policies = _policies("d-1")
    loading = CoffeeFieldFormLoadingLinkProvider(
        products=products,
        policies=policies,
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    revision = CoffeeFieldFormRevisionLinkProvider(
        products=products,
        policies=policies,
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    load_link = loading.create_link(_TECH, _MACHINE)
    rev_link = revision.create_link(_TECH, _MACHINE)
    assert load_link.url.startswith(f"{_BASE}/forms/coffee-loading?token=")
    assert rev_link.url.startswith(f"{_BASE}/forms/coffee-revision?token=")
    assert "forms.gle" not in load_link.url
    assert "google.com" not in rev_link.url

    load_token = load_link.url.split("token=", 1)[1]
    payload = verify_coffee_form_token(
        load_token,
        _SECRET,
        expected_purpose="loading",
    )
    assert payload.product_codes == ("d-1",)
    assert payload.purpose == "loading"


def test_empty_catalog_fails_issue() -> None:
    products = _MemoryProducts(())
    provider = CoffeeFieldFormRevisionLinkProvider(
        products=products,
        policies=MemoryFormInventoryPolicyStore(),
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    with pytest.raises(ValueError, match="нет видимых ингредиентов"):
        provider.create_link(_TECH, _MACHINE)


def test_issue_without_policy_fails() -> None:
    products = _MemoryProducts((_ingredient("d-1"),))
    provider = CoffeeFieldFormLoadingLinkProvider(
        products=products,
        policies=MemoryFormInventoryPolicyStore(),
        token_secret=_SECRET,
        field_forms_public_base_url=_BASE,
        clock=lambda: _CLOCK,
    )
    with pytest.raises(ValueError, match="упаковки или политики"):
        provider.create_link(_TECH, _MACHINE)


def test_google_issue_when_urls_set() -> None:
    assert coffee_field_form_issue_enabled(
        field_forms_public_base_url=_BASE,
        revision_form_url="",
        loading_form_url="",
    )
    assert not coffee_field_form_issue_enabled(
        field_forms_public_base_url=_BASE,
        revision_form_url="https://forms.gle/rev",
        loading_form_url="",
    )
    assert not coffee_field_form_issue_enabled(
        field_forms_public_base_url="",
        revision_form_url="",
        loading_form_url="",
    )
