from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.micromarket_loading import (
    MicromarketPlanogramLine,
    planogram_line_ms_catalog_codes,
)
from src.application.product_identity import DomainProduct, catalog_codes_of
from src.application.product_identity.ports import DomainProductStore, ProcurementMirrorStore
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.interfaces.admin.domain_products_view import format_procurement_price
from src.interfaces.admin.routes.micromarket_planogram_parse import _format_price_rub_ui

_EM_DASH = "—"

_MISSING_PRODUCT_LABEL = "Товар не найден"


@beartype
@dataclass(frozen=True, slots=True)
class _PlanogramRowView:
    domain_product_id: str
    product_name: str
    product_number: str
    linked: bool
    unlinked: bool
    missing_product: bool
    legacy_code: str
    legacy_label: str
    target_qty: int
    price_rub: str
    kit_group_id: int | None
    active: bool
    pending_exit: bool
    stock_qty_display: str
    last_buy_display: str
    price_origin: str = "manual"
    domain_price_display: str = _EM_DASH


@beartype
@dataclass(frozen=True, slots=True)
class _ShelfBlockView:
    kit_group_id: int
    label: str
    form_index: int
    rows: tuple[_PlanogramRowView, ...]


@beartype
@dataclass(frozen=True, slots=True)
class _ShelfSelectOption:
    kit_group_id: int
    label: str


@beartype
def _stock_qty_display(
    *,
    stock: MicromarketDeviceStock | None,
    product_code: str,
) -> str:
    code = product_code.strip()
    if not code or stock is None:
        return _EM_DASH
    qty = stock.qty(code)
    if qty == qty.to_integral_value():
        return str(int(qty))
    return format(qty, "f").rstrip("0").rstrip(".")


@beartype
def _last_buy_display(
    *,
    catalog_code: str | None,
    mirrors: ProcurementMirrorStore | None,
) -> str:
    code = (catalog_code or "").strip()
    if not code or mirrors is None:
        return _EM_DASH
    mirror = mirrors.get(code)
    if mirror is None or mirror.last_buy_price is None:
        return _EM_DASH
    return format_procurement_price(mirror.last_buy_price)


@beartype
def _last_buy_for_line(
    line: MicromarketPlanogramLine | None,
    *,
    products: DomainProductStore | None,
    mirrors: ProcurementMirrorStore | None,
) -> str:
    if line is None:
        return _EM_DASH
    for catalog_code in planogram_line_ms_catalog_codes(
        products,
        product_code=line.product_code,
        domain_product_id=line.domain_product_id,
    ):
        display = _last_buy_display(catalog_code=catalog_code, mirrors=mirrors)
        if display != _EM_DASH:
            return display
    return _EM_DASH


@beartype
def _last_buy_for_product(
    product: DomainProduct,
    *,
    mirrors: ProcurementMirrorStore | None,
) -> str:
    for code in catalog_codes_of(product):
        display = _last_buy_display(catalog_code=code, mirrors=mirrors)
        if display != _EM_DASH:
            return display
    return _last_buy_display(catalog_code=product.catalog_code, mirrors=mirrors)


@beartype
def _row_view_for_line(
    line: MicromarketPlanogramLine | None,
    *,
    products: DomainProductStore | None,
    names_by_code: Mapping[str, str],
    stock: MicromarketDeviceStock | None,
    mirrors: ProcurementMirrorStore | None,
) -> _PlanogramRowView:
    if line is None:
        return _PlanogramRowView(
            domain_product_id="",
            product_name="",
            product_number="",
            linked=True,
            unlinked=False,
            missing_product=False,
            legacy_code="",
            legacy_label="",
            target_qty=0,
            price_rub="",
            kit_group_id=None,
            active=True,
            pending_exit=False,
            stock_qty_display=_EM_DASH,
            last_buy_display=_EM_DASH,
        )

    domain_id = (line.domain_product_id or "").strip()
    code = line.product_code.strip()
    if domain_id:
        product = products.get(domain_id) if products is not None else None
        if product is None:
            return _PlanogramRowView(
                domain_product_id=domain_id,
                product_name=_MISSING_PRODUCT_LABEL,
                product_number="",
                linked=False,
                unlinked=True,
                missing_product=True,
                legacy_code="",
                legacy_label="",
                target_qty=line.target_qty,
                price_rub=_format_price_rub_ui(line.price_rub),
                kit_group_id=line.kit_group_id,
                active=line.active,
                pending_exit=line.pending_exit,
                stock_qty_display=_EM_DASH,
                last_buy_display=_EM_DASH,
                price_origin=line.price_origin,
            )
        linked = bool(product.catalog_code)
        stock_code = (product.number or product.catalog_code or "").strip()
        return _PlanogramRowView(
            domain_product_id=product.domain_product_id,
            product_name=product.name,
            product_number=product.number,
            linked=linked,
            unlinked=not linked,
            missing_product=False,
            legacy_code="",
            legacy_label="",
            target_qty=line.target_qty,
            price_rub=_format_price_rub_ui(line.price_rub),
            kit_group_id=line.kit_group_id,
            active=line.active,
            pending_exit=line.pending_exit,
            stock_qty_display=_stock_qty_display(stock=stock, product_code=stock_code),
            last_buy_display=_last_buy_for_line(
                line,
                products=products,
                mirrors=mirrors,
            ),
            price_origin=line.price_origin,
        )

    if code:
        mapped: DomainProduct | None = None
        if products is not None:
            mapped = products.get_by_catalog_code(code)
        if mapped is not None:
            stock_code = (mapped.number or code).strip()
            return _PlanogramRowView(
                domain_product_id=mapped.domain_product_id,
                product_name=mapped.name,
                product_number=mapped.number,
                linked=True,
                unlinked=False,
                missing_product=False,
                legacy_code="",
                legacy_label="",
                target_qty=line.target_qty,
                price_rub=_format_price_rub_ui(line.price_rub),
                kit_group_id=line.kit_group_id,
                active=line.active,
                pending_exit=line.pending_exit,
                stock_qty_display=_stock_qty_display(stock=stock, product_code=stock_code),
                last_buy_display=_last_buy_for_line(
                    line,
                    products=products,
                    mirrors=mirrors,
                ),
                price_origin=line.price_origin,
            )
        return _PlanogramRowView(
            domain_product_id="",
            product_name="",
            product_number="",
            linked=True,
            unlinked=False,
            missing_product=False,
            legacy_code=code,
            legacy_label=names_by_code.get(code, ""),
            target_qty=line.target_qty,
            price_rub=_format_price_rub_ui(line.price_rub),
            kit_group_id=line.kit_group_id,
            active=line.active,
            pending_exit=line.pending_exit,
            stock_qty_display=_stock_qty_display(stock=stock, product_code=code),
            last_buy_display=_last_buy_for_line(
                line,
                products=products,
                mirrors=mirrors,
            ),
            price_origin=line.price_origin,
        )

    return _PlanogramRowView(
        domain_product_id="",
        product_name="",
        product_number="",
        linked=True,
        unlinked=False,
        missing_product=False,
        legacy_code="",
        legacy_label="",
        target_qty=line.target_qty,
        price_rub=_format_price_rub_ui(line.price_rub),
        kit_group_id=line.kit_group_id,
        active=line.active,
        pending_exit=line.pending_exit,
        stock_qty_display=_EM_DASH,
        last_buy_display=_EM_DASH,
        price_origin=line.price_origin,
    )


@beartype
def _shelf_label(
    kit_group_id: int,
    *,
    kit_groups: Sequence[tuple[int, str]],
) -> str:
    for group_id, group_name in kit_groups:
        if group_id == kit_group_id:
            return group_name
    return f"Полка Kit #{kit_group_id}"
