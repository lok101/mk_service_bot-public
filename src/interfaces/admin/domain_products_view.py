from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.product_identity import (
    CatalogCandidatesImportResult,
    DomainProduct,
    DomainProductImportResult,
    DomainProductRow,
    describe_domain_product,
    list_domain_products,
)
from src.application.product_identity.ports import (
    CatalogProductLookup,
    DomainProductStore,
    ProcurementMirrorStore,
)
from src.interfaces.admin.clock_display import format_admin_moment

_EM_DASH = "—"


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductListRowView:
    domain_product_id: str
    number: str
    name: str
    catalog_code: str | None
    catalog_name: str | None
    state: str
    supplier_display: str


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductsListView:
    rows: tuple[DomainProductListRowView, ...]
    procurement_mirror_enabled: bool


@beartype
def build_domain_products_list_view(
    *,
    store: DomainProductStore,
    lookup: CatalogProductLookup,
    mirror_enabled: bool = False,
    mirrors: ProcurementMirrorStore | None = None,
) -> DomainProductsListView:
    rows = list_domain_products("all", store=store, lookup=lookup)
    ordered = tuple(sorted(rows, key=lambda row: (row.name.casefold(), row.number)))
    view_rows = tuple(
        _list_row(row, mirror_enabled=mirror_enabled, mirrors=mirrors) for row in ordered
    )
    return DomainProductsListView(
        rows=view_rows,
        procurement_mirror_enabled=mirror_enabled,
    )


def _list_row(
    row: DomainProductRow,
    *,
    mirror_enabled: bool,
    mirrors: ProcurementMirrorStore | None,
) -> DomainProductListRowView:
    supplier = _EM_DASH
    if mirror_enabled and mirrors is not None and row.catalog_code:
        mirror = mirrors.get(row.catalog_code)
        if mirror is not None and mirror.supplier_name:
            supplier = mirror.supplier_name
    return DomainProductListRowView(
        domain_product_id=row.domain_product_id,
        number=row.number,
        name=row.name,
        catalog_code=row.catalog_code,
        catalog_name=row.catalog_name,
        state=row.state,
        supplier_display=supplier,
    )


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductImportResultView:
    created: int
    linked: int
    unchanged: int
    failure_lines: tuple[str, ...]


@beartype
def build_import_result_view(
    result: DomainProductImportResult,
    *,
    file_phrase: str | None = None,
) -> DomainProductImportResultView:
    if file_phrase is not None:
        return DomainProductImportResultView(
            created=0,
            linked=0,
            unchanged=0,
            failure_lines=(file_phrase,),
        )
    failure_lines: list[str] = []
    for failure in result.failures:
        name = failure.name.strip()
        if name:
            failure_lines.append(f"Строка {failure.line_number}, {name} — {failure.message}")
        else:
            failure_lines.append(f"Строка {failure.line_number} — {failure.message}")
    return DomainProductImportResultView(
        created=result.created,
        linked=result.linked,
        unchanged=result.unchanged,
        failure_lines=tuple(failure_lines),
    )


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCandidatesImportResultView:
    created: int
    unchanged: int
    failure_lines: tuple[str, ...]


@beartype
def build_catalog_candidates_import_result_view(
    result: CatalogCandidatesImportResult,
) -> CatalogCandidatesImportResultView:
    failure_lines = tuple(f"Код {failure.code} — {failure.message}" for failure in result.failures)
    return CatalogCandidatesImportResultView(
        created=result.created,
        unchanged=result.unchanged,
        failure_lines=failure_lines,
    )


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductEditorView:
    is_new: bool
    domain_product_id: str
    number: str
    name: str
    catalog_code: str
    catalog_name: str
    state: str
    catalog_fetched_at: str = ""
    catalog_sync_error: str = ""
    catalog_refresh_enabled: bool = False
    show_procurement: bool = False
    procurement_supplier: str = _EM_DASH
    procurement_price: str = _EM_DASH
    procurement_moment: str = _EM_DASH


@beartype
def empty_domain_product_editor() -> DomainProductEditorView:
    return DomainProductEditorView(
        is_new=True,
        domain_product_id="",
        number="",
        name="",
        catalog_code="",
        catalog_name="",
        state="",
    )


@beartype
def editor_from_product(
    product: DomainProduct,
    *,
    lookup: CatalogProductLookup,
    mirror_enabled: bool = False,
    mirrors: ProcurementMirrorStore | None = None,
    timezone: ZoneInfo | None = None,
) -> DomainProductEditorView:
    row = describe_domain_product(product, lookup=lookup)
    supplier = _EM_DASH
    price = _EM_DASH
    moment = _EM_DASH
    if mirror_enabled:
        mirror = None
        if mirrors is not None and row.catalog_code:
            mirror = mirrors.get(row.catalog_code)
        if mirror is not None:
            if mirror.supplier_name:
                supplier = mirror.supplier_name
            if mirror.last_buy_price is not None:
                price = format_procurement_price(mirror.last_buy_price)
        if timezone is not None:
            moment = format_admin_moment(
                None if mirror is None else mirror.supply_moment,
                timezone,
            )
    return DomainProductEditorView(
        is_new=False,
        domain_product_id=row.domain_product_id,
        number=row.number,
        name=row.name,
        catalog_code=row.catalog_code or "",
        catalog_name=row.catalog_name or "",
        state=row.state,
        show_procurement=mirror_enabled,
        procurement_supplier=supplier,
        procurement_price=price,
        procurement_moment=moment,
    )


def format_procurement_price(price: Decimal) -> str:
    """Format last buy price for admin UI (same as domain-products card)."""
    return f"{price:.2f}".replace(".", ",")
