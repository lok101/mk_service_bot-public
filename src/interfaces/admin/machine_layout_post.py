from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from beartype import beartype

from src.application.master_data import MachineKind, MasterMachine, MasterMachineStore
from src.application.matrix_automation import SaveSnackLayoutInput, SnackPlanogramMerge
from src.application.product_identity.ports import DomainProductStore
from src.interfaces.admin.machine_layout_parse import (
    LayoutFormParseError,
    ParsedPlanogramForm,
    parse_positive_int,
)
from src.interfaces.admin.machine_layout_render import (
    MISSING_PRODUCT_LABEL,
    LayoutProductOption,
    PlanogramSlotView,
    SnackPlanogramProfileView,
    build_planogram_slots_from_anchor_map,
    layout_product_options_json,
)


@beartype
def _submitted_anchor_map(
    *,
    shelf_indices: Sequence[str],
    slot_indices: Sequence[str],
    line_numbers: Sequence[str],
    product_codes: Sequence[str],
    product_names: Sequence[str],
    options_by_code: Mapping[str, LayoutProductOption],
    domain_product_ids: Sequence[str] | None = None,
    products: DomainProductStore | None = None,
) -> dict[tuple[int, int], tuple[str, str, str, str, bool, bool]]:
    ids = list(domain_product_ids) if domain_product_ids is not None else [""] * len(product_codes)
    if not (
        len(shelf_indices)
        == len(slot_indices)
        == len(line_numbers)
        == len(product_codes)
        == len(product_names)
        == len(ids)
    ):
        raise LayoutFormParseError(
            "planogram form arrays must have equal length",
            code="invalid_layout_form",
        )
    submitted: dict[tuple[int, int], tuple[str, str, str, str, bool, bool]] = {}
    for shelf_raw, slot_raw, line_raw, code_raw, name_raw, domain_raw in zip(
        shelf_indices,
        slot_indices,
        line_numbers,
        product_codes,
        product_names,
        ids,
        strict=True,
    ):
        code = code_raw.strip()
        name = name_raw.strip()
        domain_id = domain_raw.strip()
        if not code and not name and not domain_id:
            continue
        if not shelf_raw.strip().isdigit() or not slot_raw.strip().isdigit():
            continue
        shelf_index = int(shelf_raw.strip())
        slot_index = int(slot_raw.strip())
        if domain_id:
            product = products.get(domain_id) if products is not None else None
            if product is None:
                submitted[(shelf_index, slot_index)] = (
                    line_raw,
                    "",
                    MISSING_PRODUCT_LABEL,
                    domain_id,
                    True,
                    True,
                )
            else:
                catalog_code = (product.catalog_code or "").strip()
                linked = bool(catalog_code)
                submitted[(shelf_index, slot_index)] = (
                    line_raw,
                    catalog_code if linked else "",
                    product.name,
                    domain_id,
                    not linked,
                    False,
                )
            continue
        if code and code in options_by_code:
            product_name = options_by_code[code].display_name
        else:
            product_name = name
        submitted[(shelf_index, slot_index)] = (
            line_raw,
            code,
            product_name,
            "",
            False,
            False,
        )
    return submitted


@beartype
def build_planogram_view_from_submitted_fields(
    *,
    machine: MasterMachine,
    machines: MasterMachineStore,
    shelf_count_raw: str,
    slots_per_shelf_raw: str,
    shelf_indices: Sequence[str],
    slot_indices: Sequence[str],
    line_numbers: Sequence[str],
    product_codes: Sequence[str],
    product_names: Sequence[str],
    merge_shelves: Sequence[str],
    merge_slots: Sequence[str],
    matrix_multiplier_raw: str,
    auto_sync_enabled: bool,
    product_options: tuple[LayoutProductOption, ...],
    auto_sync_allowed: bool = True,
    domain_product_ids: Sequence[str] | None = None,
    products: DomainProductStore | None = None,
) -> SnackPlanogramProfileView:
    """Re-render planogram from POST fields without strict anchor validation."""
    if len(merge_shelves) != len(merge_slots):
        raise LayoutFormParseError(
            "planogram merge arrays must have equal length",
            code="invalid_layout_form",
        )
    shelf_count = parse_positive_int(shelf_count_raw, field_name="shelf_count")
    slots_per_shelf = parse_positive_int(slots_per_shelf_raw, field_name="slots_per_shelf")
    merges: list[SnackPlanogramMerge] = []
    for shelf_raw, slot_raw in zip(merge_shelves, merge_slots, strict=True):
        if not shelf_raw.strip().isdigit() or not slot_raw.strip().isdigit():
            raise LayoutFormParseError(
                "merge shelf/slot must be non-negative integers",
                code="invalid_merge_anchor",
            )
        merges.append(
            SnackPlanogramMerge(
                shelf_index=int(shelf_raw.strip()),
                slot_index=int(slot_raw.strip()),
            )
        )
    options_by_code = {option.product_code: option for option in product_options}
    submitted_by_anchor = _submitted_anchor_map(
        shelf_indices=shelf_indices,
        slot_indices=slot_indices,
        line_numbers=line_numbers,
        product_codes=product_codes,
        product_names=product_names,
        options_by_code=options_by_code,
        domain_product_ids=domain_product_ids,
        products=products,
    )
    slots = build_planogram_slots_from_anchor_map(
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        merges=tuple(merges),
        cell_by_anchor=submitted_by_anchor,
        options_by_code=options_by_code,
    )
    copy_sources = tuple(
        sorted(
            (m.machine_id.value, m.machine_id.value)
            for m in machines.list_all()
            if m.kind is MachineKind.SNACK and m.machine_id != machine.machine_id
        )
    )
    multiplier_text = matrix_multiplier_raw.strip() or "1"
    return SnackPlanogramProfileView(
        matrix_multiplier=multiplier_text,
        auto_sync_enabled=auto_sync_enabled,
        auto_sync_allowed=auto_sync_allowed,
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        slots=slots,
        product_options=product_options,
        product_options_json=layout_product_options_json(product_options),
        copy_sources=copy_sources,
    )


build_snack_planogram_profile_view_from_submitted_fields = (
    build_planogram_view_from_submitted_fields
)


@beartype
def merge_domain_product_slot_fields(
    *,
    slots: tuple[PlanogramSlotView, ...],
    resolved: tuple[PlanogramSlotView, ...],
) -> tuple[PlanogramSlotView, ...]:
    """Overlay domain-product identity from resolved slots onto hydrated chips."""
    by_pos = {(slot.shelf_index, slot.slot_index): slot for slot in resolved}
    merged: list[PlanogramSlotView] = []
    for slot in slots:
        overlay = by_pos.get((slot.shelf_index, slot.slot_index))
        if overlay is None:
            merged.append(slot)
            continue
        if not overlay.product_code:
            merged.append(
                replace(
                    slot,
                    product_code="",
                    product_name=overlay.product_name,
                    domain_product_id=overlay.domain_product_id,
                    unlinked=overlay.unlinked,
                    missing_product=overlay.missing_product,
                    capacity_display="—",
                    purchase_display="—",
                    calculated_display="—",
                    stock_display="—" if not slot.line_number.strip() else slot.stock_display,
                    price_diff=False,
                )
            )
            continue
        keep_chips = slot.product_code == overlay.product_code
        merged.append(
            replace(
                slot,
                product_code=overlay.product_code,
                product_name=overlay.product_name,
                domain_product_id=overlay.domain_product_id,
                unlinked=overlay.unlinked,
                missing_product=overlay.missing_product,
                capacity_display=slot.capacity_display if keep_chips else overlay.capacity_display,
                purchase_display=slot.purchase_display if keep_chips else overlay.purchase_display,
                calculated_display=(
                    slot.calculated_display if keep_chips else overlay.calculated_display
                ),
            )
        )
    return tuple(merged)


@beartype
def build_save_snack_layout_input_from_parsed_planogram(
    *,
    machine_code: str,
    matrix_multiplier: Decimal,
    auto_sync_enabled: bool,
    parsed: ParsedPlanogramForm,
    actor_telegram_user_id: int,
) -> SaveSnackLayoutInput:
    return SaveSnackLayoutInput(
        machine_code=machine_code,
        matrix_multiplier=matrix_multiplier,
        auto_sync_enabled=auto_sync_enabled,
        shelf_count=parsed.shelf_count,
        slots_per_shelf=parsed.slots_per_shelf,
        merges=parsed.merges,
        anchors=parsed.anchors,
        actor_telegram_user_id=actor_telegram_user_id,
    )


@beartype
def layout_section_visible(*, layout_master_enabled: bool, machine: MasterMachine) -> bool:
    return layout_master_enabled and machine.kind is MachineKind.SNACK
