from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.product_identity import DomainProductKind
from src.application.product_identity.ports import DomainProductStore

__all__ = ["PlanogramProductOption", "planogram_product_options"]


@beartype
@dataclass(frozen=True, slots=True)
class PlanogramProductOption:
    domain_product_id: str
    name: str
    number: str
    linked: bool


@beartype
def planogram_product_options(
    store: DomainProductStore,
    *,
    kind: DomainProductKind = "micromarket",
) -> tuple[PlanogramProductOption, ...]:
    return tuple(
        PlanogramProductOption(
            domain_product_id=product.domain_product_id,
            name=product.name,
            number=product.number,
            linked=bool(product.catalog_code),
        )
        for product in store.list_visible()
        if product.kind == kind
    )
