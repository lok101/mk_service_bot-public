from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import asdict, replace

from beartype import beartype
from fastapi import Request
from fastapi.responses import Response

from src.application.master_data import MachineKind, MasterDataStores, MasterMachine
from src.application.micromarket_loading import (
    EmptyProcurementMirrorStore,
    GetMicromarketPlanogram,
    InMemoryMicromarketMachineMultiplierStore,
    InMemoryMicromarketProductMultiplierStore,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    ShopListPublishStatus,
    assemble_planogram_shelves,
    planogram_line_sort_key,
    preview_calculated_sell_for_line,
)
from src.application.product_identity.ports import DomainProductStore, ProcurementMirrorStore
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.http_common import (
    planogram_static_context,
)
from src.interfaces.admin.master_data_view import machine_profile_display_name
from src.interfaces.admin.planogram_product_options import planogram_product_options
from src.interfaces.admin.routes.micromarket_planogram_access import (
    _catalog_options,
    _machine_multiplier_display,
)
from src.interfaces.admin.routes.micromarket_planogram_rows import (
    _EM_DASH,
    _last_buy_for_product,
    _PlanogramRowView,
    _row_view_for_line,
    _shelf_label,
    _ShelfBlockView,
    _ShelfSelectOption,
)

_UNGROUPED_LABEL = "Без полки"

_SUBMITTED_SHELVES: ContextVar[tuple[MicromarketPlanogramShelf, ...] | None] = ContextVar(
    "planogram_submitted_shelves",
    default=None,
)

_SUBMITTED_SHELVES_SET: ContextVar[bool] = ContextVar(
    "planogram_submitted_shelves_set",
    default=False,
)


@beartype
def _derive_legacy_shelves(
    lines: Sequence[MicromarketPlanogramLine],
    *,
    products: DomainProductStore | None,
    names_by_code: Mapping[str, str],
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
    for shelf_id in shelf_ids:
        by_shelf[shelf_id].sort(
            key=lambda line: planogram_line_sort_key(
                line, products=products, catalog_names=names_by_code
            )
        )
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
    ordered_shelves = sorted(shelves, key=lambda shelf: shelf.sort_order)
    by_shelf: dict[int, list[MicromarketPlanogramLine]] = {
        shelf.kit_group_id: [] for shelf in ordered_shelves
    }
    ungrouped: list[MicromarketPlanogramLine] = []
    for line in sorted(lines, key=lambda item: item.sort_order):
        group_id = line.kit_group_id
        if isinstance(group_id, int) and group_id in by_shelf:
            by_shelf[group_id].append(line)
        else:
            ungrouped.append(line)
    return by_shelf, ungrouped


@beartype
def _planogram_tab_context(
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    error: str | None = None,
    notice: str | None = None,
    submitted_lines: Sequence[MicromarketPlanogramLine] | None = None,
    path_allowed_codes: frozenset[str] | None = None,
) -> dict[str, object]:
    store = deps.micromarket_planogram_store
    assert store is not None
    doc = GetMicromarketPlanogram(store=store).execute(machine.machine_id.value)
    if submitted_lines is not None:
        lines = tuple(submitted_lines)
    else:
        lines = doc.lines if doc is not None else ()
    options = _catalog_options(deps, path_allowed_codes=path_allowed_codes)
    names_by_code = {option.product_code: option.name for option in options}
    products = deps.domain_product_store
    loaded = deps.load_kit_product_groups()
    kit_groups_error = loaded[0]
    kit_groups = loaded[1]
    kit_groups_warning = loaded[2] if len(loaded) > 2 else ""

    if _SUBMITTED_SHELVES_SET.get():
        submitted = _SUBMITTED_SHELVES.get() or ()
        display_shelves = assemble_planogram_shelves(
            tuple(shelf.kit_group_id for shelf in submitted),
            lines,
        )
        by_shelf, ungrouped_lines = _partition_recorded_shelves(display_shelves, lines)
    elif submitted_lines is None and doc is not None and doc.shelves is None:
        display_shelves, by_shelf, ungrouped_lines = _derive_legacy_shelves(
            lines, products=products, names_by_code=names_by_code
        )
    elif doc is not None and doc.shelves is not None and submitted_lines is None:
        display_shelves = doc.shelves
        by_shelf, ungrouped_lines = _partition_recorded_shelves(display_shelves, lines)
    elif submitted_lines is not None:
        # submitted lines without shelves flag — treat as legacy grouping of submitted
        display_shelves, by_shelf, ungrouped_lines = _derive_legacy_shelves(
            lines, products=products, names_by_code=names_by_code
        )
    else:
        display_shelves = ()
        by_shelf = {}
        ungrouped_lines = list(lines)

    shelf_select_options = (
        ()
        if kit_groups_error
        else tuple(
            _ShelfSelectOption(kit_group_id=group_id, label=group_name)
            for group_id, group_name in kit_groups
        )
    )
    stock_store = deps.micromarket_stock_store
    device_stock = stock_store.load(machine.machine_id.value) if stock_store is not None else None
    mirrors: ProcurementMirrorStore | None = (
        deps.procurement_mirror_store
        if deps.procurement_mirror_enabled and deps.procurement_mirror_store is not None
        else None
    )
    pricing_mirrors: ProcurementMirrorStore = mirrors or EmptyProcurementMirrorStore()
    rules_store = deps.micromarket_pricing_rules_store
    pricing_rules = rules_store.get() if rules_store is not None else None
    product_mult_store = (
        deps.micromarket_product_multiplier_store or InMemoryMicromarketProductMultiplierStore()
    )
    machine_mult_store = (
        deps.micromarket_machine_multiplier_store or InMemoryMicromarketMachineMultiplierStore()
    )
    machine_code = machine.machine_id.value

    def _row_with_domain(line: MicromarketPlanogramLine | None) -> _PlanogramRowView:
        row = _row_view_for_line(
            line,
            products=products,
            names_by_code=names_by_code,
            stock=device_stock,
            mirrors=mirrors,
        )
        if line is None:
            return row
        sell = preview_calculated_sell_for_line(
            line=line,
            machine_code=machine_code,
            rules=pricing_rules,
            product_multipliers=product_mult_store,
            machine_multipliers=machine_mult_store,
            mirrors=pricing_mirrors,
            products=products,
        )
        return replace(
            row,
            domain_price_display=_EM_DASH if sell is None else str(sell),
        )

    shelf_blocks: list[_ShelfBlockView] = []
    for form_index, shelf in enumerate(sorted(display_shelves, key=lambda item: item.sort_order)):
        shelf_lines = by_shelf.get(shelf.kit_group_id, [])
        shelf_blocks.append(
            _ShelfBlockView(
                kit_group_id=shelf.kit_group_id,
                label=_shelf_label(shelf.kit_group_id, kit_groups=kit_groups),
                form_index=form_index,
                rows=tuple(_row_with_domain(line) for line in shelf_lines),
            )
        )
    ungrouped_rows = tuple(_row_with_domain(line) for line in ungrouped_lines)
    empty_enroll = _row_with_domain(None)
    planogram_copy_sources = tuple(
        sorted(
            (
                other.machine_id.value,
                machine_profile_display_name(stores, other),
            )
            for other in stores.machines.list_all()
            if other.kind is MachineKind.MICRO_MARKET and other.machine_id != machine.machine_id
        )
    )

    # Flat views kept for any residual template/tests that still look at them.
    display_row_views = (
        tuple(row for block in shelf_blocks for row in (*block.rows, empty_enroll)) + ungrouped_rows
    )

    last_buy_by_domain_id: dict[str, str] = {}
    if products is not None:
        product_options = planogram_product_options(products)
        options_json = json.dumps([asdict(option) for option in product_options]).replace(
            "<", "\\u003c"
        )
        for product in products.list_visible():
            last_buy_by_domain_id[product.domain_product_id] = _last_buy_for_product(
                product,
                mirrors=mirrors,
            )
    else:
        options_json = "[]"
    last_buy_prices_json = json.dumps(last_buy_by_domain_id, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    if doc is not None:
        shop_list_status = doc.shop_list_status
        shop_list_status_label = shop_list_status.label_ru
        shop_list_error = doc.shop_list_error
    else:
        shop_list_status = ShopListPublishStatus.UNPUBLISHED
        shop_list_status_label = shop_list_status.label_ru
        shop_list_error = ""
    shop_list_publishing = shop_list_status is ShopListPublishStatus.PUBLISHING
    shop_list_published = shop_list_status is ShopListPublishStatus.PUBLISHED
    context: dict[str, object] = {
        "machine": machine,
        "display_name": machine_profile_display_name(stores, machine),
        "lines": lines,
        "display_row_views": display_row_views,
        "shelf_blocks": tuple(shelf_blocks),
        "ungrouped_rows": ungrouped_rows,
        "ungrouped_label": _UNGROUPED_LABEL,
        "empty_enroll_row": empty_enroll,
        "shelf_select_options": shelf_select_options,
        "planogram_copy_sources": planogram_copy_sources,
        "planogram_product_options_json": options_json,
        "planogram_last_buy_prices_json": last_buy_prices_json,
        "names_by_code": names_by_code,
        "error": error,
        "notice": notice,
        "shop_list_status_label": shop_list_status_label,
        "shop_list_error": shop_list_error,
        "shop_list_publishing": shop_list_publishing,
        "shop_list_published": shop_list_published,
        "kit_groups": kit_groups,
        "kit_groups_error": kit_groups_error,
        "kit_groups_warning": kit_groups_warning,
        "machine_price_multiplier_display": _machine_multiplier_display(deps, machine),
    }
    context.update(planogram_static_context())
    return context


@beartype
def _render_planogram_page(
    request: Request,
    deps: AdminHttpDeps,
    stores: MasterDataStores,
    machine: MasterMachine,
    *,
    error: str | None = None,
    notice: str | None = None,
    submitted_lines: Sequence[MicromarketPlanogramLine] | None = None,
    submitted_shelves: Sequence[MicromarketPlanogramShelf] | None = None,
    status_code: int = 200,
    path_allowed_codes: frozenset[str] | None = None,
) -> Response:
    from src.interfaces.admin.routes.micromarket_planograms import _render_fridge_workspace

    shelves_token = _SUBMITTED_SHELVES.set(
        tuple(submitted_shelves) if submitted_shelves is not None else None
    )
    set_token = _SUBMITTED_SHELVES_SET.set(submitted_shelves is not None)
    try:
        return _render_fridge_workspace(
            request,
            deps,
            stores,
            machine,
            active_tab="planogram",
            path_allowed_codes=path_allowed_codes,
            status_code=status_code,
            error=error,
            notice=notice,
            submitted_lines=submitted_lines,
        )
    finally:
        _SUBMITTED_SHELVES.reset(shelves_token)
        _SUBMITTED_SHELVES_SET.reset(set_token)
