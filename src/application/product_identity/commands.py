from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from beartype import beartype

from src.application.product_identity.models import (
    AMBIGUOUS_NAME_TEXT,
    CARD_TAKEN_TEXT,
    CODE_MISSING_TEXT,
    EMPTY_NAME_TEXT,
    NUMBER_NOT_ISSUED_TEXT,
    OTHER_CARD_TEXT,
    PACKAGING_REQUIRED_TEXT,
    SECOND_LINK_TEXT,
    WRONG_CONTOUR_TEXT,
    DomainProduct,
    DomainProductConflict,
    DomainProductContour,
    DomainProductImportFailure,
    DomainProductImportResult,
    DomainProductImportRow,
    DomainProductKind,
    DomainProductRejected,
    catalog_codes_of,
    packaging_is_form_ready,
)
from src.application.product_identity.number import canonical_domain_number
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.application.product_identity.sync_procurement_mirror import SyncProcurementMirror
from src.domain.product_catalog import ProductUnit

_LOGGER = logging.getLogger(__name__)

_ATTEMPT_LIMIT = 1000
_COFFEE_KINDS = frozenset({"coffee_ingredient", "coffee_drink"})


@beartype
def allocate_domain_number(
    issued: tuple[str, ...],
    *,
    collides: Callable[[str], bool],
) -> str:
    candidate = _max_canonical_suffix(issued) + 1
    for offset in range(_ATTEMPT_LIMIT):
        number = f"d-{candidate + offset}"
        if not collides(number):
            return number
    raise DomainProductRejected(NUMBER_NOT_ISSUED_TEXT)


@beartype
def create_domain_product(
    name: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    kind: DomainProductKind = "micromarket",
    unit: ProductUnit | None = None,
    pack_size: Decimal | None = None,
) -> DomainProduct:
    trimmed = name.strip()
    if not trimmed:
        raise DomainProductRejected(EMPTY_NAME_TEXT)
    if kind == "coffee_ingredient" and not packaging_is_form_ready(
        unit=unit,
        pack_size=pack_size,
    ):
        raise DomainProductRejected(PACKAGING_REQUIRED_TEXT)
    reserved: list[str] = []
    for _attempt in range(_ATTEMPT_LIMIT):
        number = allocate_domain_number(
            (*store.numbers(), *reserved),
            collides=lookup.number_collides,
        )
        product = DomainProduct(
            domain_product_id=uuid4().hex,
            number=number,
            name=trimmed,
            catalog_code=None,
            hidden=False,
            kind=kind,
            unit=unit,
            pack_size=pack_size,
        )
        try:
            store.insert(product)
        except DomainProductConflict as error:
            if error.field != "number":
                raise
            reserved.append(number)
            continue
        return product
    raise DomainProductRejected(NUMBER_NOT_ISSUED_TEXT)


@beartype
def set_domain_product_packaging(
    domain_product_id: str,
    *,
    unit: ProductUnit,
    pack_size: Decimal,
    store: DomainProductStore,
) -> DomainProduct:
    if not packaging_is_form_ready(unit=unit, pack_size=pack_size):
        raise DomainProductRejected(PACKAGING_REQUIRED_TEXT)
    product = _require_product(store, domain_product_id)
    if product.kind != "coffee_ingredient":
        raise DomainProductRejected(WRONG_CONTOUR_TEXT)
    if product.unit is unit and product.pack_size == pack_size:
        return product
    updated = replace(product, unit=unit, pack_size=pack_size)
    store.save(updated)
    return updated


@beartype
def add_domain_product_link(
    domain_product_id: str,
    code: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    procurement_sync: SyncProcurementMirror | None = None,
) -> DomainProduct:
    trimmed = code.strip()
    if not trimmed or lookup.get(trimmed) is None:
        raise DomainProductRejected(CODE_MISSING_TEXT)
    product = _require_product(store, domain_product_id)
    existing = catalog_codes_of(product)
    if trimmed in existing:
        return product
    if product.kind == "micromarket" and existing:
        raise DomainProductRejected(SECOND_LINK_TEXT)
    holder = store.get_by_catalog_code(trimmed)
    if holder is not None and holder.domain_product_id != product.domain_product_id:
        raise DomainProductRejected(CARD_TAKEN_TEXT)
    if product.catalog_code is None:
        updated = replace(product, catalog_code=trimmed)
        old: str | None = None
    else:
        updated = replace(product, extra_catalog_codes=(*product.extra_catalog_codes, trimmed))
        old = None
    try:
        store.save(updated)
    except DomainProductConflict as error:
        if error.field == "catalog_code":
            raise DomainProductRejected(CARD_TAKEN_TEXT) from error
        raise
    if procurement_sync is not None and old is None and product.catalog_code is None:
        try:
            procurement_sync.sync_codes(None, trimmed)
        except Exception:
            _LOGGER.exception("procurement_mirror_point_sync_failed")
    return updated


@beartype
def set_legacy_ms_code(
    domain_product_id: str,
    code: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> DomainProduct:
    trimmed = code.strip()
    if not trimmed or lookup.get(trimmed) is None:
        raise DomainProductRejected(CODE_MISSING_TEXT)
    product = _require_product(store, domain_product_id)
    if product.kind != "coffee_drink":
        raise DomainProductRejected(OTHER_CARD_TEXT)
    if product.legacy_ms_code == trimmed:
        return product
    holder = store.get_by_catalog_code(trimmed)
    if holder is not None and holder.domain_product_id != product.domain_product_id:
        raise DomainProductRejected(CARD_TAKEN_TEXT)
    updated = replace(product, legacy_ms_code=trimmed)
    try:
        store.save(updated)
    except DomainProductConflict as error:
        if error.field == "catalog_code":
            raise DomainProductRejected(CARD_TAKEN_TEXT) from error
        raise
    return updated


@beartype
def link_domain_product(
    domain_product_id: str,
    code: str,
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    procurement_sync: SyncProcurementMirror | None = None,
) -> DomainProduct:
    trimmed = code.strip()
    if not trimmed or lookup.get(trimmed) is None:
        raise DomainProductRejected(CODE_MISSING_TEXT)
    product = _require_product(store, domain_product_id)
    _require_contour(product, "micromarket")
    if product.catalog_code == trimmed:
        return product
    old = product.catalog_code
    holder = store.get_by_catalog_code(trimmed)
    if holder is not None and holder.domain_product_id != product.domain_product_id:
        raise DomainProductRejected(CARD_TAKEN_TEXT)
    updated = replace(product, catalog_code=trimmed)
    try:
        store.save(updated)
    except DomainProductConflict as error:
        if error.field == "catalog_code":
            raise DomainProductRejected(CARD_TAKEN_TEXT) from error
        raise
    if procurement_sync is not None:
        try:
            procurement_sync.sync_codes(old, trimmed)
        except Exception:
            _LOGGER.exception("procurement_mirror_point_sync_failed")
    return updated


@beartype
def unlink_domain_product(
    domain_product_id: str,
    *,
    store: DomainProductStore,
    procurement_sync: SyncProcurementMirror | None = None,
) -> DomainProduct:
    product = _require_product(store, domain_product_id)
    old = product.catalog_code
    if old is None and not product.extra_catalog_codes:
        return product
    updated = replace(product, catalog_code=None, extra_catalog_codes=())
    store.save(updated)
    if procurement_sync is not None:
        procurement_sync.sync_codes(old)
    return updated


@beartype
def remove_domain_product_link(
    domain_product_id: str,
    code: str,
    *,
    store: DomainProductStore,
    procurement_sync: SyncProcurementMirror | None = None,
) -> DomainProduct:
    trimmed = code.strip()
    product = _require_product(store, domain_product_id)
    codes = catalog_codes_of(product)
    if not trimmed or trimmed not in codes:
        return product
    remaining = tuple(item for item in codes if item != trimmed)
    old_primary = product.catalog_code
    if not remaining:
        updated = replace(product, catalog_code=None, extra_catalog_codes=())
    else:
        updated = replace(
            product,
            catalog_code=remaining[0],
            extra_catalog_codes=remaining[1:],
        )
    store.save(updated)
    if procurement_sync is not None and old_primary == trimmed:
        procurement_sync.sync_codes(old_primary, remaining[0] if remaining else None)
    return updated


@beartype
def rename_domain_product(
    domain_product_id: str,
    name: str,
    *,
    store: DomainProductStore,
    contour: DomainProductContour = "micromarket",
) -> DomainProduct:
    trimmed = name.strip()
    if not trimmed:
        raise DomainProductRejected(EMPTY_NAME_TEXT)
    product = _require_product(store, domain_product_id)
    _require_contour(product, contour)
    if product.name == trimmed:
        return product
    updated = replace(product, name=trimmed)
    store.save(updated)
    return updated


@beartype
def hide_domain_product(
    domain_product_id: str,
    *,
    store: DomainProductStore,
    contour: DomainProductContour = "micromarket",
) -> DomainProduct:
    product = _require_product(store, domain_product_id)
    _require_contour(product, contour)
    if product.hidden:
        return product
    updated = replace(product, hidden=True)
    store.save(updated)
    return updated


@beartype
def unhide_domain_product(
    domain_product_id: str,
    *,
    store: DomainProductStore,
) -> DomainProduct:
    product = _require_product(store, domain_product_id)
    if not product.hidden:
        return product
    updated = replace(product, hidden=False)
    store.save(updated)
    return updated


@beartype
def import_domain_products(
    rows: tuple[DomainProductImportRow, ...],
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    procurement_sync: SyncProcurementMirror | None = None,
) -> DomainProductImportResult:
    created = 0
    linked = 0
    unchanged = 0
    failures: list[DomainProductImportFailure] = []

    for row in rows:
        name = row.name.strip()
        catalog_code = row.catalog_code.strip()
        if not name and not catalog_code:
            continue
        if not name:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=EMPTY_NAME_TEXT,
                )
            )
            continue

        matches = tuple(
            product
            for product in store.list_visible()
            if product.name == name and product.kind == "micromarket"
        )
        if len(matches) > 1:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=AMBIGUOUS_NAME_TEXT,
                )
            )
            continue

        if len(matches) == 1:
            product = matches[0]
            if not catalog_code or product.catalog_code == catalog_code:
                unchanged += 1
                continue
            if product.catalog_code is not None:
                failures.append(
                    DomainProductImportFailure(
                        line_number=row.line_number,
                        name=name,
                        message=OTHER_CARD_TEXT,
                    )
                )
                continue
            try:
                link_domain_product(
                    product.domain_product_id,
                    catalog_code,
                    store=store,
                    lookup=lookup,
                    procurement_sync=procurement_sync,
                )
            except DomainProductRejected as error:
                failures.append(
                    DomainProductImportFailure(
                        line_number=row.line_number,
                        name=name,
                        message=error.message,
                    )
                )
                continue
            linked += 1
            continue

        if catalog_code and lookup.get(catalog_code) is None:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=CODE_MISSING_TEXT,
                )
            )
            continue
        if catalog_code and store.get_by_catalog_code(catalog_code) is not None:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=CARD_TAKEN_TEXT,
                )
            )
            continue

        try:
            product = create_domain_product(name, store=store, lookup=lookup)
        except DomainProductRejected as error:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=error.message,
                )
            )
            continue
        created += 1

        if not catalog_code:
            continue
        try:
            link_domain_product(
                product.domain_product_id,
                catalog_code,
                store=store,
                lookup=lookup,
                procurement_sync=procurement_sync,
            )
        except DomainProductRejected as error:
            failures.append(
                DomainProductImportFailure(
                    line_number=row.line_number,
                    name=name,
                    message=error.message,
                )
            )
            continue
        linked += 1

    return DomainProductImportResult(
        created=created,
        linked=linked,
        unchanged=unchanged,
        failures=tuple(failures),
    )


def _require_contour(product: DomainProduct, contour: DomainProductContour) -> None:
    is_coffee = product.kind in _COFFEE_KINDS
    if contour == "micromarket" and is_coffee:
        raise DomainProductRejected(WRONG_CONTOUR_TEXT)
    if contour == "coffee" and not is_coffee:
        raise DomainProductRejected(WRONG_CONTOUR_TEXT)


def _require_product(store: DomainProductStore, domain_product_id: str) -> DomainProduct:
    product = store.get(domain_product_id)
    if product is None:
        raise DomainProductRejected("Товар не найден.")
    return product


def _max_canonical_suffix(numbers: tuple[str, ...]) -> int:
    maximum = 0
    for number in numbers:
        canonical = canonical_domain_number(number)
        if canonical is None:
            continue
        suffix = int(canonical.removeprefix("d-"))
        if suffix > maximum:
            maximum = suffix
    return maximum
