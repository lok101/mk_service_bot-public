from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_inventory_policy import (
    FormInventoryPolicyProfileId,
    FormInventoryPolicyStore,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.product_catalog import (
    ProductSpec,
    default_moysklad_quantity_factor,
)
from src.domain.quantities import QuantityInputMode


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeDomainIngredientProductCodeResolver:
    """Resolve FieldForm line titles (domain numbers) to ProductSpec keyed by d-….

    Unit/pack come from the domain coffee ingredient; min/max from the form
    inventory policy profile. Sheets catalog is not SoT for packaging (ADR-0091).
    """

    products: DomainProductStore
    policies: FormInventoryPolicyStore
    profile_id: FormInventoryPolicyProfileId

    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec:
        number = product_name.strip()
        if not number:
            raise ValueError("Product name must not be empty")
        product = self.products.get_by_number(number)
        if product is None or product.kind != "coffee_ingredient" or product.hidden:
            raise ValueError(f"Product spec not found for name {number!r}")
        if product.unit is None or product.pack_size is None or product.pack_size <= 0:
            raise ValueError(f"Packaging missing for coffee ingredient {number!r}")
        line = self.policies.get_line(self.profile_id, number)
        if line is None:
            raise ValueError(f"Form inventory policy missing for {number!r}")
        profile = self.policies.get_profile(self.profile_id)
        allow_fraction = profile is not None and profile.input_mode is QuantityInputMode.BASE_STOCK
        name = product.name.strip() or number
        return ProductSpec(
            product_code=number,
            name=name,
            unit=product.unit,
            pack_size=product.pack_size,
            min_stock=line.min_qty,
            max_stock=line.max_qty,
            allow_fraction=allow_fraction,
            moysklad_quantity_factor=default_moysklad_quantity_factor(product.unit),
        )
