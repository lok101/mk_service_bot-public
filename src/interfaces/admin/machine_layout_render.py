from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from beartype import beartype

from src.application.master_data import MachineKind, MasterMachine, MasterMachineStore
from src.application.matrix_automation import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
    SnackPlanogramMerge,
    default_planogram_dimensions,
)
from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.product_identity.ports import DomainProductStore
from src.domain.matrix_pricing import BaseMarginParams, calculate_sell_price

MISSING_PRODUCT_LABEL = "Товар не найден"


@beartype
@dataclass(frozen=True, slots=True)
class LayoutProductOption:
    product_code: str
    display_name: str
    capacity_display: str  # "" | "—" | "0" | "12" …


@beartype
@dataclass(frozen=True, slots=True)
class PlanogramSlotView:
    shelf_index: int
    slot_index: int
    is_anchor: bool
    grid_column_span: int  # 1 | 2
    merge_eligible: bool
    merge_checked: bool
    span_merge_anchor_slot: int
    span_toggle_direction: str  # "left" | "right"
    line_number: str
    product_code: str
    product_name: str
    stock_display: str
    capacity_display: str
    purchase_display: str
    calculated_display: str
    current_display: str
    stock_overflow: bool
    price_diff: bool
    domain_product_id: str = ""
    unlinked: bool = False
    missing_product: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class SnackPlanogramProfileView:
    matrix_multiplier: str
    auto_sync_enabled: bool
    auto_sync_allowed: bool
    shelf_count: int
    slots_per_shelf: int
    slots: tuple[PlanogramSlotView, ...]
    product_options: tuple[LayoutProductOption, ...]
    product_options_json: str
    copy_sources: tuple[tuple[str, str], ...]


@beartype
def capacity_display_for(*, product_code: str, catalog_capacity: int | None) -> str:
    """Return \"\" / \"—\" / str(capacity) per spec rules."""
    if not product_code:
        return ""
    if catalog_capacity is None:
        return "—"
    return str(catalog_capacity)


@beartype
def build_layout_product_options(
    *,
    known_codes: frozenset[str],
    ms_names: Mapping[str, str],
    catalog_by_code: Mapping[str, tuple[str, int]],
) -> tuple[LayoutProductOption, ...]:
    """One option per known code; catalog display_name/capacity preferred."""
    options: list[LayoutProductOption] = []
    for code in known_codes:
        catalog = catalog_by_code.get(code)
        if catalog is not None:
            display_name, capacity = catalog
            capacity_display = capacity_display_for(product_code=code, catalog_capacity=capacity)
        else:
            display_name = ms_names.get(code, "")
            capacity_display = capacity_display_for(product_code=code, catalog_capacity=None)
        options.append(
            LayoutProductOption(
                product_code=code,
                display_name=display_name,
                capacity_display=capacity_display,
            )
        )
    return tuple(sorted(options, key=lambda o: (o.display_name.casefold(), o.product_code)))


@beartype
def layout_product_options_json(options: Sequence[LayoutProductOption]) -> str:
    """Stable JSON for #layout-product-options-json; ``<`` → ``\\u003c`` (HTML-safe)."""
    payload = {
        option.product_code: {
            "name": option.display_name,
            "capacity": option.capacity_display,
        }
        for option in options
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


@beartype
def name_index_from_options(
    options: Sequence[LayoutProductOption],
) -> dict[str, frozenset[str]]:
    """casefold(display_name) → frozenset of product_codes."""
    index: dict[str, set[str]] = {}
    for option in options:
        key = option.display_name.casefold()
        index.setdefault(key, set()).add(option.product_code)
    return {key: frozenset(codes) for key, codes in index.items()}


@beartype
def _normalize_merges(
    merges: Sequence[SnackPlanogramMerge | tuple[int, int]],
) -> tuple[SnackPlanogramMerge, ...]:
    normalized: list[SnackPlanogramMerge] = []
    for merge in merges:
        if isinstance(merge, SnackPlanogramMerge):
            normalized.append(merge)
        else:
            normalized.append(SnackPlanogramMerge(shelf_index=merge[0], slot_index=merge[1]))
    return tuple(normalized)


@beartype
def _absorbed_slots(
    merges: tuple[SnackPlanogramMerge, ...],
) -> frozenset[tuple[int, int]]:
    return frozenset((merge.shelf_index, merge.slot_index + 1) for merge in merges)


@beartype
def _merge_anchor_keys(
    merges: tuple[SnackPlanogramMerge, ...],
) -> frozenset[tuple[int, int]]:
    return frozenset((merge.shelf_index, merge.slot_index) for merge in merges)


@beartype
def _anchor_positions_row_major(
    *,
    shelf_count: int,
    slots_per_shelf: int,
    absorbed: frozenset[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    positions: list[tuple[int, int]] = []
    for shelf_index in range(shelf_count):
        for slot_index in range(slots_per_shelf):
            if (shelf_index, slot_index) in absorbed:
                continue
            positions.append((shelf_index, slot_index))
    return tuple(positions)


@beartype
def _cells_have_all_coords(cells: Sequence[SnackMachineLayoutCell]) -> bool:
    if not cells:
        return True
    return all(cell.shelf_index is not None and cell.slot_index is not None for cell in cells)


@beartype
def _resolve_cell_fields(
    cell: SnackMachineLayoutCell,
    *,
    options_by_code: Mapping[str, LayoutProductOption],
    products: DomainProductStore | None,
) -> tuple[str, str, str, str, bool, bool]:
    """line, chip code, name, domain_product_id, unlinked, missing_product."""
    domain_id = (cell.domain_product_id or "").strip()
    legacy_code = (cell.product_code or "").strip()
    if domain_id:
        product = products.get(domain_id) if products is not None else None
        if product is None:
            return (
                str(cell.line_number),
                "",
                MISSING_PRODUCT_LABEL,
                domain_id,
                True,
                True,
            )
        catalog_code = (product.catalog_code or "").strip()
        linked = bool(catalog_code)
        return (
            str(cell.line_number),
            catalog_code if linked else "",
            product.name,
            product.domain_product_id,
            not linked,
            False,
        )
    if legacy_code:
        mapped = products.get_by_catalog_code(legacy_code) if products is not None else None
        if mapped is not None:
            catalog_code = (mapped.catalog_code or "").strip() or legacy_code
            return (
                str(cell.line_number),
                catalog_code,
                mapped.name,
                mapped.domain_product_id,
                False,
                False,
            )
        option = options_by_code.get(legacy_code)
        product_name = option.display_name if option is not None else ""
        return str(cell.line_number), legacy_code, product_name, "", False, False
    return str(cell.line_number), "", "", "", False, False


@beartype
def _assign_cells_by_coordinates(
    *,
    cells: Sequence[SnackMachineLayoutCell],
    options_by_code: Mapping[str, LayoutProductOption],
    products: DomainProductStore | None,
) -> dict[tuple[int, int], tuple[str, str, str, str, bool, bool]]:
    assignment: dict[tuple[int, int], tuple[str, str, str, str, bool, bool]] = {}
    for cell in cells:
        domain_id = (cell.domain_product_id or "").strip()
        code = (cell.product_code or "").strip()
        if not domain_id and not code:
            continue
        if cell.shelf_index is None or cell.slot_index is None:
            continue
        assignment[(cell.shelf_index, cell.slot_index)] = _resolve_cell_fields(
            cell,
            options_by_code=options_by_code,
            products=products,
        )
    return assignment


@beartype
def _assign_cells_row_major(
    *,
    shelf_count: int,
    slots_per_shelf: int,
    merges: tuple[SnackPlanogramMerge, ...],
    cells: Sequence[SnackMachineLayoutCell],
    options_by_code: Mapping[str, LayoutProductOption],
    products: DomainProductStore | None,
) -> dict[tuple[int, int], tuple[str, str, str, str, bool, bool]]:
    """Legacy fallback: map cells without coords to anchors in row-major order."""
    absorbed = _absorbed_slots(merges)
    positions = _anchor_positions_row_major(
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        absorbed=absorbed,
    )
    assignment: dict[tuple[int, int], tuple[str, str, str, str, bool, bool]] = {}
    position_iter = iter(positions)
    for cell in cells:
        try:
            position = next(position_iter)
        except StopIteration:
            break
        assignment[position] = _resolve_cell_fields(
            cell,
            options_by_code=options_by_code,
            products=products,
        )
    return assignment


@beartype
def _stock_display(
    *,
    stock_qty: Decimal | None,
    capacity: int | None,
    has_line_and_product: bool,
) -> tuple[str, bool]:
    if not has_line_and_product:
        return "—", False
    if stock_qty is None or capacity is None:
        return "—", False
    stock_int = int(stock_qty)
    overflow = stock_int > capacity
    return str(stock_int), overflow


@beartype
def _purchase_display(purchase: Decimal | None, *, has_product: bool) -> str:
    if not has_product or purchase is None:
        return "—"
    return str(int(purchase.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


@beartype
def _capacity_int_from_display(capacity_display: str) -> int | None:
    if not capacity_display or capacity_display == "—":
        return None
    try:
        return int(capacity_display)
    except ValueError:
        return None


@beartype
def _planogram_slot_with_chips(
    *,
    shelf_index: int = 0,
    slot_index: int = 0,
    is_anchor: bool = True,
    grid_column_span: int = 1,
    merge_eligible: bool = False,
    merge_checked: bool = False,
    span_merge_anchor_slot: int = 0,
    span_toggle_direction: str = "right",
    line_number: str,
    product_code: str,
    product_name: str = "",
    stock_qty: Decimal | None,
    capacity: int | None,
    purchase: Decimal | None,
    calculated: str,
    current: str,
    domain_product_id: str = "",
    unlinked: bool = False,
    missing_product: bool = False,
) -> PlanogramSlotView:
    has_product = bool(product_code.strip())
    has_line_and_product = bool(line_number.strip() and product_code.strip())
    stock_display, stock_overflow = _stock_display(
        stock_qty=stock_qty,
        capacity=capacity,
        has_line_and_product=has_line_and_product,
    )
    capacity_display = "—" if not has_product else (str(capacity) if capacity is not None else "—")
    purchase_display = _purchase_display(purchase, has_product=has_product)
    price_diff = (
        has_line_and_product and calculated != "—" and current != "—" and calculated != current
    )
    return PlanogramSlotView(
        shelf_index=shelf_index,
        slot_index=slot_index,
        is_anchor=is_anchor,
        grid_column_span=grid_column_span,
        merge_eligible=merge_eligible,
        merge_checked=merge_checked,
        span_merge_anchor_slot=span_merge_anchor_slot,
        span_toggle_direction=span_toggle_direction,
        line_number=line_number,
        product_code=product_code,
        product_name=product_name,
        stock_display=stock_display,
        capacity_display=capacity_display,
        purchase_display=purchase_display,
        calculated_display=calculated,
        current_display=current,
        stock_overflow=stock_overflow,
        price_diff=price_diff,
        domain_product_id=domain_product_id,
        unlinked=unlinked,
        missing_product=missing_product,
    )


@beartype
def build_planogram_slots_from_anchor_map(
    *,
    shelf_count: int,
    slots_per_shelf: int,
    merges: tuple[SnackPlanogramMerge, ...],
    cell_by_anchor: Mapping[tuple[int, int], tuple[str, str, str, str, bool, bool]],
    options_by_code: Mapping[str, LayoutProductOption],
) -> tuple[PlanogramSlotView, ...]:
    absorbed = _absorbed_slots(merges)
    merge_anchors = _merge_anchor_keys(merges)
    slots: list[PlanogramSlotView] = []
    for shelf_index in range(shelf_count):
        for slot_index in range(slots_per_shelf):
            if (shelf_index, slot_index) in absorbed:
                continue
            (
                line_number,
                product_code,
                product_name,
                domain_product_id,
                unlinked,
                missing_product,
            ) = cell_by_anchor.get(
                (shelf_index, slot_index),
                ("", "", "", "", False, False),
            )
            if not product_name and product_code:
                option = options_by_code.get(product_code)
                product_name = option.display_name if option is not None else ""
            merge_checked = (shelf_index, slot_index) in merge_anchors
            grid_column_span = 2 if merge_checked else 1
            span_merge_anchor_slot = slot_index if slot_index % 2 == 0 else slot_index - 1
            span_toggle_direction = "right" if slot_index % 2 == 0 else "left"
            merge_eligible = True
            slots.append(
                _planogram_slot_with_chips(
                    shelf_index=shelf_index,
                    slot_index=slot_index,
                    merge_eligible=merge_eligible,
                    merge_checked=merge_checked,
                    span_merge_anchor_slot=span_merge_anchor_slot,
                    span_toggle_direction=span_toggle_direction,
                    grid_column_span=grid_column_span,
                    line_number=line_number,
                    product_code=product_code,
                    product_name=product_name,
                    stock_qty=None,
                    capacity=None,
                    purchase=None,
                    calculated="—",
                    current="—",
                    domain_product_id=domain_product_id,
                    unlinked=unlinked,
                    missing_product=missing_product,
                )
            )
    return tuple(slots)


@beartype
def build_planogram_slots(
    *,
    shelf_count: int,
    slots_per_shelf: int,
    merges: Sequence[SnackPlanogramMerge | tuple[int, int]],
    cells: Sequence[SnackMachineLayoutCell],
    options_by_code: Mapping[str, LayoutProductOption],
    products: DomainProductStore | None = None,
) -> tuple[PlanogramSlotView, ...]:
    """Build anchor slots for the 2D planogram grid."""
    normalized_merges = _normalize_merges(merges)
    if _cells_have_all_coords(cells):
        cell_by_anchor = _assign_cells_by_coordinates(
            cells=cells,
            options_by_code=options_by_code,
            products=products,
        )
    else:
        cell_by_anchor = _assign_cells_row_major(
            shelf_count=shelf_count,
            slots_per_shelf=slots_per_shelf,
            merges=normalized_merges,
            cells=cells,
            options_by_code=options_by_code,
            products=products,
        )
    return build_planogram_slots_from_anchor_map(
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        merges=normalized_merges,
        cell_by_anchor=cell_by_anchor,
        options_by_code=options_by_code,
    )


@beartype
def _live_price_display(
    *,
    product_code: str,
    matrix_multiplier: Decimal,
    base_margin: BaseMarginParams | None,
    purchases: Mapping[str, Decimal] | None,
    product_multipliers: Mapping[str, Decimal],
) -> str:
    if not product_code or base_margin is None or purchases is None:
        return "—"
    purchase = purchases.get(product_code)
    if purchase is None:
        return "—"
    product_multiplier = product_multipliers.get(product_code, Decimal("1"))
    return str(
        calculate_sell_price(
            purchase=purchase,
            product_multiplier=product_multiplier,
            matrix_multiplier=matrix_multiplier,
            params=base_margin,
        )
    )


@beartype
def _hydrate_planogram_slot(
    slot: PlanogramSlotView,
    *,
    options_by_code: Mapping[str, LayoutProductOption],
    matrix_multiplier: Decimal,
    base_margin: BaseMarginParams | None,
    purchases: Mapping[str, Decimal] | None,
    product_multipliers: Mapping[str, Decimal],
    stock_by_line: Mapping[int, Decimal],
    snapshot_deploy_by_line: Mapping[int, Decimal],
) -> PlanogramSlotView:
    line_text = slot.line_number.strip()
    code = slot.product_code.strip()
    line_int: int | None = None
    if line_text.isdigit():
        line_int = int(line_text)

    option = options_by_code.get(code)
    capacity = _capacity_int_from_display(
        option.capacity_display if option is not None else "—",
    )
    stock_qty = stock_by_line.get(line_int) if line_int is not None else None
    purchase = purchases.get(code) if purchases is not None else None
    calculated = _live_price_display(
        product_code=code,
        matrix_multiplier=matrix_multiplier,
        base_margin=base_margin,
        purchases=purchases,
        product_multipliers=product_multipliers,
    )
    current = "—"
    if line_int is not None:
        deploy = snapshot_deploy_by_line.get(line_int)
        if deploy is not None:
            current = str(deploy)

    return _planogram_slot_with_chips(
        shelf_index=slot.shelf_index,
        slot_index=slot.slot_index,
        is_anchor=slot.is_anchor,
        grid_column_span=slot.grid_column_span,
        merge_eligible=slot.merge_eligible,
        merge_checked=slot.merge_checked,
        span_merge_anchor_slot=slot.span_merge_anchor_slot,
        span_toggle_direction=slot.span_toggle_direction,
        line_number=slot.line_number,
        product_code=slot.product_code,
        product_name=slot.product_name,
        stock_qty=stock_qty,
        capacity=capacity,
        purchase=purchase,
        calculated=calculated,
        current=current,
        domain_product_id=slot.domain_product_id,
        unlinked=slot.unlinked,
        missing_product=slot.missing_product,
    )


@beartype
def build_snack_layout_profile_view(
    *,
    machine: MasterMachine,
    layout_store: SnackMachineLayoutStore,
    machines: MasterMachineStore,
    product_options: tuple[LayoutProductOption, ...] = (),
    base_margin: BaseMarginParams | None = None,
    purchases: Mapping[str, Decimal] | None = None,
    product_multipliers: Mapping[str, Decimal] | None = None,
    auto_sync_allowed: bool = True,
    stock_by_line: Mapping[int, Decimal] | None = None,
    snapshot_deploy_by_line: Mapping[int, Decimal] | None = None,
    products: DomainProductStore | None = None,
) -> SnackPlanogramProfileView | None:
    if machine.kind is not MachineKind.SNACK:
        return None
    machine_code = machine.machine_id.value
    layout = layout_store.get(machine_code)
    if layout is None:
        shelf_count, slots_per_shelf = default_planogram_dimensions()
        layout = SnackMachineLayout(
            machine_code=machine_code,
            logical_matrix_name=machine_code,
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            shelf_count=shelf_count,
            slots_per_shelf=slots_per_shelf,
            merges=(),
            cells=(),
        )
    options_by_code = {option.product_code: option for option in product_options}
    multipliers = dict(product_multipliers or {})
    stock_map = dict(stock_by_line or {})
    snapshot_map = dict(snapshot_deploy_by_line or {})
    raw_slots = build_planogram_slots(
        shelf_count=layout.shelf_count,
        slots_per_shelf=layout.slots_per_shelf,
        merges=layout.merges,
        cells=layout.cells,
        options_by_code=options_by_code,
        products=products,
    )
    slots = tuple(
        _hydrate_planogram_slot(
            slot,
            options_by_code=options_by_code,
            matrix_multiplier=layout.matrix_multiplier,
            base_margin=base_margin,
            purchases=purchases,
            product_multipliers=multipliers,
            stock_by_line=stock_map,
            snapshot_deploy_by_line=snapshot_map,
        )
        for slot in raw_slots
    )
    copy_sources = tuple(
        sorted(
            (m.machine_id.value, m.machine_id.value)
            for m in machines.list_all()
            if m.kind is MachineKind.SNACK and m.machine_id != machine.machine_id
        )
    )
    return SnackPlanogramProfileView(
        matrix_multiplier=format(layout.matrix_multiplier, "f"),
        auto_sync_enabled=layout.auto_sync_enabled,
        auto_sync_allowed=auto_sync_allowed,
        shelf_count=layout.shelf_count,
        slots_per_shelf=layout.slots_per_shelf,
        slots=slots,
        product_options=product_options,
        product_options_json=layout_product_options_json(product_options),
        copy_sources=copy_sources,
    )
