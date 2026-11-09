from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.product_identity.models import CatalogProduct, DomainProduct
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore

_SEARCH_CAP = 50
_WINDOW_CAP = 8

HOLD_REASON: dict[str, str] = {
    "hold_unlinked": "domain_product_unlinked",
    "hold_broken": "domain_product_link_broken",
    "hold_archived": "domain_product_catalog_archived",
    "hold_unknown_number": "unknown_domain_number",
}

_COFFEE_PANEL_KINDS = frozenset({"coffee_drink", "coffee_ingredient"})

HOLD_TEXT: dict[str, str] = {
    "domain_product_unlinked": "Товар не связан с карточкой каталога, продажа не записана.",
    "domain_product_link_broken": "Связь с карточкой каталога порвана, продажа не записана.",
    "domain_product_catalog_archived": "Карточка каталога в архиве, продажа не записана.",
    "unknown_domain_number": "На карточке код доменного номера, а товара с таким номером нет.",
}


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductRow:
    domain_product_id: str
    number: str
    name: str
    catalog_code: str | None
    catalog_name: str | None
    state: str


@beartype
def list_domain_products(
    filter: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> tuple[DomainProductRow, ...]:
    """Retail micromarket list; coffee drink/ingredient live on coffee admin tabs only."""
    rows: list[DomainProductRow] = []
    for product in store.list_visible():
        if product.hidden:
            continue
        if product.kind in _COFFEE_PANEL_KINDS:
            continue
        if filter == "unlinked" and product.catalog_code:
            continue
        if filter == "linked" and not product.catalog_code:
            continue
        rows.append(_row(product, lookup))
    return tuple(rows)


@beartype
def search_catalog_cards(
    query: str,
    *,
    lookup: CatalogProductLookup,
) -> tuple[CatalogProduct, ...]:
    return lookup.search(query)[:_SEARCH_CAP]


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCardHit:
    code: str
    name: str
    archived: bool


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCardWindow:
    hits: tuple[CatalogCardHit, ...]
    truncated: bool


@beartype
def catalog_card_window(
    query: str,
    *,
    cards: tuple[CatalogProduct, ...],
) -> CatalogCardWindow:
    needle = query.strip().casefold()
    if not needle:
        return CatalogCardWindow(hits=(), truncated=False)
    exact: list[CatalogProduct] = []
    rest: list[CatalogProduct] = []
    for card in cards:
        code_fold = card.code.strip().casefold()
        if code_fold == needle:
            exact.append(card)
        elif needle in code_fold or needle in card.name.casefold():
            rest.append(card)
    ordered = [*exact, *rest]
    return CatalogCardWindow(
        hits=tuple(
            CatalogCardHit(code=card.code, name=card.name, archived=card.archived)
            for card in ordered[:_WINDOW_CAP]
        ),
        truncated=len(ordered) > _WINDOW_CAP,
    )


@beartype
def hold_alert_text(reason: str) -> str | None:
    return HOLD_TEXT.get(reason)


@beartype
def describe_domain_product(
    product: DomainProduct,
    *,
    lookup: CatalogProductLookup,
) -> DomainProductRow:
    return _row(product, lookup)


def _row(product: DomainProduct, lookup: CatalogProductLookup) -> DomainProductRow:
    code = product.catalog_code or None
    card = lookup.get(code) if code is not None else None
    if code is None:
        state = "нет связи"
        catalog_name = None
    elif card is None:
        state = "порвана"
        catalog_name = None
    elif card.archived:
        state = "архив"
        catalog_name = card.name
    else:
        state = "связана"
        catalog_name = card.name
    return DomainProductRow(
        domain_product_id=product.domain_product_id,
        number=product.number,
        name=product.name,
        catalog_code=code,
        catalog_name=catalog_name,
        state=state,
    )
