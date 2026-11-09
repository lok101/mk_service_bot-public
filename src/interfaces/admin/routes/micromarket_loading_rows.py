from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading import MicromarketLoadingPreviewRow
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    MicromarketAssemblyOrder,
)
from src.domain.micromarket_loading.order import DraftLine
from src.domain.micromarket_loading.quantities import initial_launch_qty
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.micromarket_loading_support import (
    _LAUNCH_STEPPER_MAX,
    _UNGROUPED_SHELF_LABEL,
    _qty_display,
)


@beartype
@dataclass(frozen=True, slots=True)
class LoadingRowView:
    product_code: str
    name: str
    stock_qty: Decimal
    target_qty: int
    need_qty: Decimal
    launch_qty: Decimal
    warehouse_qty: Decimal | None = None
    warehouse_qty_display: str = "—"
    kit_group_id: int | None = None
    shelf_title: str = ""
    shelf_sort_order: int = 0
    need_from_live: bool = False
    launch_stepper_max: int = _LAUNCH_STEPPER_MAX
    assembly_qty: Decimal = Decimal("0")
    assembly_qty_locked: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class LoadingShelfSection:
    kit_group_id: int | None
    title: str
    sort_order: int
    rows: tuple[LoadingRowView, ...]


@beartype
def _occupied_assembly_catalog_codes(
    orders: Sequence[MicromarketAssemblyOrder],
) -> frozenset[str]:
    codes: set[str] = set()
    for order in orders:
        if order.status is not AssemblyOrderStatus.OPEN:
            continue
        for line in order.lines:
            codes.add(line.catalog_code)
    return frozenset(codes)


@beartype
def _initial_assembly_qty(
    *,
    need_qty: Decimal,
    warehouse_qty: Decimal | None,
) -> Decimal:
    if warehouse_qty is None:
        return need_qty if need_qty > 0 else Decimal("0")
    return initial_launch_qty(need_qty=need_qty, warehouse_qty=warehouse_qty)


@beartype
def _loading_row_view(
    row: MicromarketLoadingPreviewRow,
    *,
    draft_by_code: dict[str, DraftLine],
    warehouse_by_product: Mapping[str, Decimal] | None,
    resolved_need: Decimal,
    need_from_live: bool,
    shelf_title: str,
    shelf_sort_order: int,
    assembly_qty_locked: bool = False,
) -> LoadingRowView:
    draft = draft_by_code.get(row.product_code)
    warehouse_qty: Decimal | None = None
    if warehouse_by_product is not None and row.product_code in warehouse_by_product:
        warehouse_qty = warehouse_by_product[row.product_code]
    if draft is not None:
        computed_launch = draft.launch_qty
    elif warehouse_qty is not None:
        computed_launch = initial_launch_qty(
            need_qty=resolved_need,
            warehouse_qty=warehouse_qty,
        )
    else:
        computed_launch = resolved_need
    if assembly_qty_locked:
        assembly_qty = Decimal("0")
    else:
        assembly_qty = _initial_assembly_qty(
            need_qty=resolved_need,
            warehouse_qty=warehouse_qty,
        )
    stepper_ceiling = max(
        _LAUNCH_STEPPER_MAX,
        int(computed_launch.to_integral_value()),
        int(resolved_need.to_integral_value()),
        int(assembly_qty.to_integral_value()),
        int((warehouse_qty or Decimal("0")).to_integral_value()),
    )
    return LoadingRowView(
        product_code=row.product_code,
        name=row.name,
        stock_qty=row.stock_qty,
        target_qty=row.target_qty,
        need_qty=resolved_need,
        launch_qty=computed_launch,
        warehouse_qty=warehouse_qty,
        warehouse_qty_display=_qty_display(warehouse_qty),
        kit_group_id=row.kit_group_id,
        shelf_title=shelf_title,
        shelf_sort_order=shelf_sort_order,
        need_from_live=need_from_live,
        launch_stepper_max=stepper_ceiling,
        assembly_qty=assembly_qty,
        assembly_qty_locked=assembly_qty_locked,
    )


@beartype
def _shelf_title_for_group(kit_group_id: int, names: Mapping[int, str]) -> str:
    name = names.get(kit_group_id, "").strip()
    if name:
        return name
    return f"Полка Kit #{kit_group_id}"


@beartype
def _loading_shelf_meta(
    deps: AdminHttpDeps,
    machine_code: str,
    *,
    preview_group_ids: Sequence[int] = (),
) -> tuple[dict[int, int], dict[int, str], dict[int, str]]:
    """Return shelf_sort_by_id, titles_by_id, and kit_names for loading sections."""
    store = deps.micromarket_planogram_store
    assert store is not None
    doc = store.get(machine_code)
    loaded = deps.load_kit_product_groups()
    # Tests may stub a plain tuple; production returns KitProductGroupsLoad.
    kit_names = {group_id: label for group_id, label in loaded[1]}
    shelf_sort: dict[int, int] = {}
    if doc is not None and doc.shelves is not None:
        for shelf in doc.shelves:
            shelf_sort[shelf.kit_group_id] = shelf.sort_order
    elif doc is not None:
        order_index = 0
        for line in sorted(doc.lines, key=lambda item: item.sort_order):
            group_id = line.kit_group_id
            if isinstance(group_id, int) and group_id > 0 and group_id not in shelf_sort:
                shelf_sort[group_id] = order_index
                order_index += 1
    next_order = max(shelf_sort.values(), default=-1) + 1
    for group_id in preview_group_ids:
        if group_id > 0 and group_id not in shelf_sort:
            shelf_sort[group_id] = next_order
            next_order += 1
    titles = {group_id: _shelf_title_for_group(group_id, kit_names) for group_id in shelf_sort}
    return shelf_sort, titles, kit_names


@beartype
def _group_loading_sections(
    rows: Sequence[LoadingRowView],
    *,
    kit_names: Mapping[int, str] | None = None,
) -> tuple[LoadingShelfSection, ...]:
    names = kit_names or {}
    buckets: dict[int | None, list[LoadingRowView]] = {}
    order: list[int | None] = []
    for row in rows:
        group_id = row.kit_group_id
        key = group_id if isinstance(group_id, int) and group_id > 0 else None
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)

    def sort_key(group_id: int | None) -> tuple[int, int]:
        if group_id is None:
            return (1, 10**9)
        sample = buckets[group_id][0]
        return (0, sample.shelf_sort_order)

    ordered_keys = sorted(order, key=sort_key)
    sections: list[LoadingShelfSection] = []
    for index, group_id in enumerate(ordered_keys):
        group_rows = tuple(buckets[group_id])
        if group_id is None:
            title = _UNGROUPED_SHELF_LABEL
            sort_order = 10**9
        else:
            title = group_rows[0].shelf_title or _shelf_title_for_group(group_id, names)
            sort_order = group_rows[0].shelf_sort_order
        sections.append(
            LoadingShelfSection(
                kit_group_id=group_id,
                title=title,
                sort_order=sort_order if group_id is not None else index,
                rows=group_rows,
            )
        )
    return tuple(sections)
