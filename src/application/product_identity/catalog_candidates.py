from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.product_identity.commands import create_domain_product, link_domain_product
from src.application.product_identity.models import CODE_MISSING_TEXT, DomainProductRejected
from src.application.product_identity.ports import CatalogProductLookup, DomainProductStore
from src.application.product_identity.sync_procurement_mirror import SyncProcurementMirror


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCandidate:
    code: str
    name: str
    archived: bool


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCandidatesImportFailure:
    code: str
    message: str


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCandidatesImportResult:
    created: int
    unchanged: int
    failures: tuple[CatalogCandidatesImportFailure, ...]


@beartype
def list_catalog_candidates(
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
) -> tuple[CatalogCandidate, ...]:
    candidates: list[CatalogCandidate] = []
    for card in lookup.products():
        if store.get_by_catalog_code(card.code) is not None:
            continue
        candidates.append(CatalogCandidate(code=card.code, name=card.name, archived=card.archived))
    return tuple(candidates)


@beartype
def import_catalog_candidates(
    codes: tuple[str, ...],
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    procurement_sync: SyncProcurementMirror | None = None,
) -> CatalogCandidatesImportResult:
    created = 0
    unchanged = 0
    failures: list[CatalogCandidatesImportFailure] = []

    for raw_code in codes:
        code = raw_code.strip()
        card = lookup.get(code) if code else None
        if card is None:
            failures.append(
                CatalogCandidatesImportFailure(
                    code=code or raw_code,
                    message=CODE_MISSING_TEXT,
                )
            )
            continue
        if store.get_by_catalog_code(card.code) is not None:
            unchanged += 1
            continue
        try:
            product = create_domain_product(card.name, store=store, lookup=lookup)
        except DomainProductRejected as error:
            failures.append(CatalogCandidatesImportFailure(code=card.code, message=error.message))
            continue
        try:
            link_domain_product(
                product.domain_product_id,
                card.code,
                store=store,
                lookup=lookup,
                procurement_sync=procurement_sync,
            )
        except DomainProductRejected as error:
            failures.append(CatalogCandidatesImportFailure(code=card.code, message=error.message))
            continue
        created += 1

    return CatalogCandidatesImportResult(
        created=created,
        unchanged=unchanged,
        failures=tuple(failures),
    )
