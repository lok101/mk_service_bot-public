from __future__ import annotations

from decimal import Decimal

from scripts.migrate_coffee_form_inventory_policy_lib import (
    migrate_coffee_form_inventory_from_catalog,
)
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    MemoryFormInventoryPolicyStore,
)
from src.application.product_identity.models import DomainProduct
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)


class _Catalog:
    def __init__(self, specs: dict[str, ProductSpec]) -> None:
        self._specs = specs

    def resolve_by_code(self, product_code: str) -> ProductSpec:
        key = product_code.strip().casefold()
        for code, spec in self._specs.items():
            if code.casefold() == key:
                return spec
        raise ValueError(f"missing {product_code!r}")

    def try_resolve_by_code(self, product_code: str) -> ProductSpec | None:
        try:
            return self.resolve_by_code(product_code)
        except ValueError:
            return None


def _spec(*, code: str = "ms-1", pack: str = "1000") -> ProductSpec:
    unit = ProductUnit.GRAM
    return ProductSpec(
        product_code=code,
        name="Milk",
        unit=unit,
        pack_size=Decimal(pack),
        min_stock=Decimal("0"),
        max_stock=Decimal("5000"),
        allow_fraction=True,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


def test_migrate_copies_pack_size() -> None:
    products = FakeDomainProductStore()
    product = DomainProduct(
        domain_product_id="p1",
        number="d-1",
        name="Молоко",
        catalog_code="ms-1",
        hidden=False,
        kind="coffee_ingredient",
    )
    products.insert(product)
    policies = MemoryFormInventoryPolicyStore()
    stats = migrate_coffee_form_inventory_from_catalog(
        products=products,
        catalog=_Catalog({"ms-1": _spec()}),
        policies=policies,
    )
    assert stats.packaging_updated == 1
    assert stats.policies_seeded == 1
    saved = products.get("p1")
    assert saved is not None
    assert saved.unit is ProductUnit.GRAM
    assert saved.pack_size == Decimal("1000")
    line = policies.get_line(COFFEE_LOADING_PROFILE_ID, "d-1")
    assert line is not None
    assert line.max_qty == Decimal("5000")
    assert line.radio_n == 10


def test_migrate_dry_run_empty_catalog() -> None:
    products = FakeDomainProductStore()
    policies = MemoryFormInventoryPolicyStore()
    stats = migrate_coffee_form_inventory_from_catalog(
        products=products,
        catalog=_Catalog({}),
        policies=policies,
        dry_run=True,
    )
    assert stats.scanned == 0
    assert stats.packaging_updated == 0
    assert stats.policies_seeded == 0
