from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

from src.application.product_identity.models import DomainProduct, catalog_codes_of
from src.application.product_identity.number import canonical_domain_number
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore

HoldKind = Literal[
    "hold_unlinked",
    "hold_broken",
    "hold_archived",
    "hold_unknown_number",
]


@beartype
@dataclass(frozen=True, slots=True)
class ResolveRecognized:
    domain_product_id: str
    catalog_code: str


@beartype
@dataclass(frozen=True, slots=True)
class ResolveLegacy:
    code: str


@beartype
@dataclass(frozen=True, slots=True)
class ResolveHold:
    kind: HoldKind


DomainProductResolve = ResolveRecognized | ResolveLegacy | ResolveHold


@beartype
@dataclass(frozen=True, slots=True)
class KitShopRecognized:
    domain_product_id: str
    number: str
    alias_from: str | None = None


KitShopSaleResolve = KitShopRecognized | ResolveLegacy | ResolveHold


@beartype
def resolve_sale_code(
    raw: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> DomainProductResolve:
    trimmed = raw.strip()
    canonical = canonical_domain_number(trimmed)
    if canonical is not None:
        by_number = store.get_by_number(canonical)
        if by_number is not None:
            return _branch(by_number, lookup)
    by_code = store.get_by_catalog_code(trimmed)
    if by_code is not None:
        return _branch(by_code, lookup, matched_code=trimmed)
    if canonical is not None and lookup.get(trimmed) is None:
        return ResolveHold(kind="hold_unknown_number")
    return ResolveLegacy(code=trimmed)


@beartype
def resolve_kit_shop_sale_code(
    raw: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> KitShopSaleResolve:
    trimmed = raw.strip()
    canonical = canonical_domain_number(trimmed)
    if canonical is not None:
        by_number = store.get_by_number(canonical)
        if by_number is not None:
            return KitShopRecognized(
                domain_product_id=by_number.domain_product_id,
                number=by_number.number,
            )
    by_code = store.get_by_catalog_code(trimmed)
    if by_code is not None:
        return KitShopRecognized(
            domain_product_id=by_code.domain_product_id,
            number=by_code.number,
            alias_from=trimmed,
        )
    if canonical is not None and lookup.get(trimmed) is None:
        return ResolveHold(kind="hold_unknown_number")
    return ResolveLegacy(code=trimmed)


def _kit_code_without_catalog_card(
    product: DomainProduct,
    *,
    matched_code: str | None,
) -> bool:
    """Kit bundle code stored as legacy_ms_code is not a catalog link."""
    if matched_code is None or product.legacy_ms_code != matched_code:
        return False
    return matched_code not in catalog_codes_of(product)


def _branch(
    product: DomainProduct,
    lookup: CatalogProductLookup,
    *,
    matched_code: str | None = None,
) -> DomainProductResolve:
    code: str | None
    if matched_code is not None and (
        matched_code in catalog_codes_of(product) or product.legacy_ms_code == matched_code
    ):
        code = matched_code
    else:
        codes = catalog_codes_of(product)
        code = codes[0] if codes else product.legacy_ms_code
    if code is None or code == "":
        return ResolveHold(kind="hold_unlinked")
    card = lookup.get(code)
    if card is None:
        if matched_code is not None and _kit_code_without_catalog_card(
            product,
            matched_code=matched_code,
        ):
            return ResolveLegacy(code=matched_code)
        return ResolveHold(kind="hold_broken")
    if card.archived:
        return ResolveHold(kind="hold_archived")
    return ResolveRecognized(domain_product_id=product.domain_product_id, catalog_code=code)
