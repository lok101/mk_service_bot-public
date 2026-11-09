from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    planogram_line_sort_key,
)
from src.application.micromarket_loading.sku_set import micromarket_inventory_sku_codes
from src.application.product_identity.ports import DomainProductStore

OFF_PLANOGRAM_PAGE_TITLE = "Вне планограммы"


@beartype
@dataclass(frozen=True, slots=True)
class InventoryFormPage:
    kit_group_id: int | None
    product_codes: tuple[str, ...]
    title: str


@beartype
def flatten_inventory_form_page_codes(pages: Sequence[InventoryFormPage]) -> tuple[str, ...]:
    codes: list[str] = []
    for page in pages:
        codes.extend(page.product_codes)
    return tuple(codes)


@beartype
def build_micromarket_inventory_form_pages(
    *,
    planogram: MicromarketPlanogram | None,
    stock_qty: Mapping[str, Decimal],
    products: DomainProductStore | None = None,
    kit_group_names: Mapping[int, str] | None = None,
) -> tuple[InventoryFormPage, ...]:
    lines = planogram.lines if planogram is not None else ()
    active_codes = _domain_numbers_for_lines(lines, products=products, pending_exit=False)
    pending_codes = _domain_numbers_for_lines(lines, products=products, pending_exit=True)
    sku_set = micromarket_inventory_sku_codes(
        active_planogram_codes=active_codes,
        pending_exit_planogram_codes=pending_codes,
        stock_qty=stock_qty,
    )
    if not sku_set:
        return ()

    if planogram is not None and planogram.shelves is not None:
        shelves = tuple(sorted(planogram.shelves, key=lambda shelf: shelf.sort_order))
        by_shelf, ungrouped = _partition_recorded_shelves(shelves, lines)
    elif planogram is not None:
        shelves, by_shelf, ungrouped = _derive_legacy_shelves(lines)
    else:
        shelves = ()
        by_shelf = {}
        ungrouped = list(lines)

    names = kit_group_names or {}
    pages: list[InventoryFormPage] = []
    placed: set[str] = set()
    for shelf in shelves:
        shelf_lines = by_shelf.get(shelf.kit_group_id, [])
        codes = _ordered_codes_for_lines(shelf_lines, sku_set=sku_set, products=products)
        if not codes:
            continue
        placed.update(codes)
        pages.append(
            InventoryFormPage(
                kit_group_id=shelf.kit_group_id,
                product_codes=codes,
                title=_shelf_title(shelf.kit_group_id, names),
            )
        )

    off_codes = _ordered_codes_for_lines(ungrouped, sku_set=sku_set, products=products)
    placed.update(off_codes)
    stock_only = sorted(
        (code for code in sku_set if code not in placed),
        key=lambda code: _stock_code_sort_key(code, products=products),
    )
    off_page_codes = off_codes + tuple(stock_only)
    if off_page_codes:
        pages.append(
            InventoryFormPage(
                kit_group_id=None,
                product_codes=off_page_codes,
                title=OFF_PLANOGRAM_PAGE_TITLE,
            )
        )
    return tuple(pages)


@beartype
def _shelf_title(kit_group_id: int, names: Mapping[int, str]) -> str:
    name = names.get(kit_group_id, "").strip()
    if name:
        return name
    return f"группа {kit_group_id}"


@beartype
def _domain_numbers_for_lines(
    lines: Sequence[MicromarketPlanogramLine],
    *,
    products: DomainProductStore | None,
    pending_exit: bool | None,
) -> list[str]:
    numbers: list[str] = []
    if products is None:
        return numbers
    for line in lines:
        if pending_exit is True and not line.pending_exit:
            continue
        if pending_exit is False and not line.active:
            continue
        code = _line_inventory_code(line, products=products)
        if code is not None:
            numbers.append(code)
    return numbers


@beartype
def _line_inventory_code(
    line: MicromarketPlanogramLine,
    *,
    products: DomainProductStore | None,
) -> str | None:
    if products is None:
        return None
    domain_id = (line.domain_product_id or "").strip()
    if not domain_id:
        return None
    product = products.get(domain_id)
    if product is None:
        return None
    return product.number


@beartype
def _ordered_codes_for_lines(
    lines: Sequence[MicromarketPlanogramLine],
    *,
    sku_set: frozenset[str],
    products: DomainProductStore | None,
) -> tuple[str, ...]:
    eligible: list[MicromarketPlanogramLine] = []
    for line in lines:
        code = _line_inventory_code(line, products=products)
        if code is None or code not in sku_set:
            continue
        eligible.append(line)
    active = [line for line in eligible if not line.pending_exit]
    pending = [line for line in eligible if line.pending_exit]
    active.sort(key=lambda line: planogram_line_sort_key(line, products=products))
    pending.sort(key=lambda line: planogram_line_sort_key(line, products=products))
    codes: list[str] = []
    seen: set[str] = set()
    for line in (*active, *pending):
        code = _line_inventory_code(line, products=products)
        if code is None or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return tuple(codes)


@beartype
def _stock_code_sort_key(
    code: str,
    *,
    products: DomainProductStore | None,
) -> tuple[str, str]:
    name = ""
    if products is not None:
        product = products.get_by_number(code)
        if product is not None:
            name = product.name.strip()
    normalized = (name or code).casefold().replace("ё", "е")
    return (normalized, code)


@beartype
def _derive_legacy_shelves(
    lines: Sequence[MicromarketPlanogramLine],
) -> tuple[
    tuple[MicromarketPlanogramShelf, ...],
    dict[int, list[MicromarketPlanogramLine]],
    list[MicromarketPlanogramLine],
]:
    ordered = sorted(lines, key=lambda line: line.sort_order)
    shelf_ids: list[int] = []
    seen: set[int] = set()
    for line in ordered:
        group_id = line.kit_group_id
        if isinstance(group_id, int) and group_id > 0 and group_id not in seen:
            seen.add(group_id)
            shelf_ids.append(group_id)
    by_shelf: dict[int, list[MicromarketPlanogramLine]] = {shelf_id: [] for shelf_id in shelf_ids}
    ungrouped: list[MicromarketPlanogramLine] = []
    for line in ordered:
        group_id = line.kit_group_id
        if isinstance(group_id, int) and group_id in by_shelf:
            by_shelf[group_id].append(line)
        else:
            ungrouped.append(line)
    shelves = tuple(
        MicromarketPlanogramShelf(kit_group_id=shelf_id, sort_order=index)
        for index, shelf_id in enumerate(shelf_ids)
    )
    return shelves, by_shelf, ungrouped


@beartype
def _partition_recorded_shelves(
    shelves: Sequence[MicromarketPlanogramShelf],
    lines: Sequence[MicromarketPlanogramLine],
) -> tuple[dict[int, list[MicromarketPlanogramLine]], list[MicromarketPlanogramLine]]:
    by_shelf: dict[int, list[MicromarketPlanogramLine]] = {
        shelf.kit_group_id: [] for shelf in shelves
    }
    ungrouped: list[MicromarketPlanogramLine] = []
    for line in sorted(lines, key=lambda item: item.sort_order):
        group_id = line.kit_group_id
        if isinstance(group_id, int) and group_id in by_shelf:
            by_shelf[group_id].append(line)
        else:
            ungrouped.append(line)
    return by_shelf, ungrouped
