from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.form_submissions import (
    parse_and_build_frozen_inventory_lines,
)
from src.application.form_submissions.ports import (
    ProductCodeResolver,
)
from src.domain.form_submission import FormAnswer, FrozenInventoryLine
from src.domain.ids import TechnicianId
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)

TEST_TECHNICIAN_ID = TechnicianId("001")
OTHER_TECHNICIAN_ID = TechnicianId("tech-2")


@beartype
@dataclass(frozen=True, slots=True)
class MappingProductCatalogResolver(ProductCodeResolver):
    name_to_code: dict[str, str]
    pack_size: Decimal = Decimal("20")

    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec:
        normalized = product_name.strip()
        if not normalized:
            raise ValueError("Product name must not be empty")
        try:
            product_code = self.name_to_code[normalized]
        except KeyError as error:
            raise ValueError(
                f"Product code not found for name {normalized!r}",
            ) from error
        unit = ProductUnit.GRAM
        return ProductSpec(
            product_code=product_code,
            name=normalized,
            unit=unit,
            pack_size=self.pack_size,
            min_stock=None,
            max_stock=None,
            allow_fraction=True,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        )


@beartype
@dataclass(frozen=True, slots=True)
class PassThroughProductCodeResolver(ProductCodeResolver):
    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec:
        normalized = product_name.strip()
        if not normalized:
            raise ValueError("Product name must not be empty")
        unit = ProductUnit.GRAM
        return ProductSpec(
            product_code=normalized,
            name=normalized,
            unit=unit,
            pack_size=Decimal("1"),
            min_stock=None,
            max_stock=None,
            allow_fraction=True,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        )


@beartype
def build_test_frozen_inventory_lines(
    answers: tuple[FormAnswer, ...],
    resolver: ProductCodeResolver,
    *,
    form_token_field_name: str,
    mode_purpose: str,
) -> tuple[FrozenInventoryLine, ...]:
    return parse_and_build_frozen_inventory_lines(
        product_code_resolver=resolver,
        form_token_field_name=form_token_field_name,
        answers=answers,
        mode_purpose=mode_purpose,
    )
