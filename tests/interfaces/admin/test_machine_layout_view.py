from __future__ import annotations

import json
from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import curved_margin_params

from src.application.master_data import (
    InMemoryMasterDataStores,
    MachineKind,
    MachineStatus,
    MasterMachine,
    MasterMachineStore,
)
from src.application.matrix_automation import SnackMachineLayout, SnackMachineLayoutCell
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.matrix_automation.snack_planogram import SnackPlanogramMerge
from src.application.product_identity import DomainProduct
from src.domain.ids import MachineId
from src.domain.matrix_pricing import calculate_sell_price
from src.infrastructure.product_identity import MemoryDomainProductStore
from src.interfaces.admin.machine_layout_view import (
    LayoutFormParseError,
    LayoutProductOption,
    PlanogramSlotView,
    _planogram_slot_with_chips,
    build_layout_product_options,
    build_planogram_slots,
    build_planogram_view_from_submitted_fields,
    build_snack_layout_profile_view,
    capacity_display_for,
    layout_product_options_json,
    parse_planogram_form,
)


def test_build_planogram_slots_sticky_hole_at_col_7() -> None:
    options = {
        "BATON": LayoutProductOption("BATON", "Батончик", "10"),
        "AQUA": LayoutProductOption("AQUA", "Вода", "8"),
    }
    cells = (
        SnackMachineLayoutCell(1, "BATON", 0, 0),
        SnackMachineLayoutCell(8, "AQUA", 0, 7),
    )
    slots = build_planogram_slots(
        shelf_count=1,
        slots_per_shelf=8,
        merges=(),
        cells=cells,
        options_by_code=options,
    )
    by_slot = {(s.shelf_index, s.slot_index): s for s in slots}
    assert by_slot[(0, 0)].product_code == "BATON"
    assert by_slot[(0, 7)].product_code == "AQUA"
    assert by_slot[(0, 1)].product_code == ""


def test_build_planogram_slots_legacy_row_major_fallback() -> None:
    options = {"A": LayoutProductOption("A", "A-name", "1")}
    cells = (SnackMachineLayoutCell(1, "A"),)  # no coords
    slots = build_planogram_slots(
        shelf_count=1,
        slots_per_shelf=3,
        merges=(),
        cells=cells,
        options_by_code=options,
    )
    assert slots[0].product_code == "A"
    assert slots[0].slot_index == 0


def test_build_planogram_slots_default_6x10_empty() -> None:
    slots = build_planogram_slots(
        shelf_count=6,
        slots_per_shelf=10,
        merges=(),
        cells=(),
        options_by_code={},
    )
    assert len(slots) == 60
    anchor = slots[0]
    assert anchor.shelf_index == 0 and anchor.slot_index == 0
    assert anchor.is_anchor is True
    assert anchor.grid_column_span == 1
    assert anchor.line_number == ""
    assert anchor.product_code == ""


def test_build_planogram_slots_merge_span_two_hides_right() -> None:
    slots = build_planogram_slots(
        shelf_count=1,
        slots_per_shelf=4,
        merges=(SnackPlanogramMerge(shelf_index=0, slot_index=0),),
        cells=(),
        options_by_code={},
    )
    assert len(slots) == 3
    assert slots[0].grid_column_span == 2
    assert slots[0].merge_checked is True


def test_build_planogram_slots_merged_anchor_stays_merge_eligible() -> None:
    slots = build_planogram_slots(
        shelf_count=1,
        slots_per_shelf=4,
        merges=(SnackPlanogramMerge(shelf_index=0, slot_index=0),),
        cells=(),
        options_by_code={},
    )
    assert slots[0].merge_checked is True
    assert slots[0].merge_eligible is True
    assert slots[1].slot_index == 2
    assert slots[1].merge_eligible is True
    assert slots[2].slot_index == 3
    assert slots[2].merge_eligible is True
    assert slots[2].span_toggle_direction == "left"


def test_build_planogram_slot_chips_happy_path() -> None:
    slot = _planogram_slot_with_chips(
        line_number="11",
        product_code="A",
        stock_qty=Decimal("4"),
        capacity=10,
        purchase=Decimal("45.7"),
        calculated="113",
        current="112",
    )
    assert slot.stock_display == "4"
    assert slot.purchase_display == "46"
    assert slot.price_diff is True


def test_build_planogram_slot_chips_missing_data_dash() -> None:
    slot = _planogram_slot_with_chips(
        line_number="",
        product_code="",
        stock_qty=None,
        capacity=None,
        purchase=None,
        calculated="—",
        current="—",
    )
    assert slot.stock_display == "—"
    assert slot.purchase_display == "—"


def test_planogram_slot_capacity_without_line_when_product_known() -> None:
    """happy: known SKU without line → capacity shown."""
    slot = _planogram_slot_with_chips(
        line_number="",
        product_code="A",
        stock_qty=None,
        capacity=12,
        purchase=None,
        calculated="—",
        current="—",
    )
    assert slot.capacity_display == "12"
    assert slot.stock_display == "—"


def test_planogram_slot_purchase_without_line_stock_dash() -> None:
    """happy: purchase from SKU without line; stock stays dash."""
    slot = _planogram_slot_with_chips(
        line_number="",
        product_code="A",
        stock_qty=Decimal("4"),
        capacity=10,
        purchase=Decimal("45.7"),
        calculated="113",
        current="—",
    )
    assert slot.purchase_display == "46"
    assert slot.capacity_display == "10"
    assert slot.stock_display == "—"
    assert slot.price_diff is False


def test_planogram_slot_chips_no_product_stay_dash() -> None:
    """edge: no product_code → capacity/purchase dash even if capacity int given."""
    slot = _planogram_slot_with_chips(
        line_number="11",
        product_code="",
        stock_qty=Decimal("1"),
        capacity=10,
        purchase=Decimal("10"),
        calculated="—",
        current="—",
    )
    assert slot.capacity_display == "—"
    assert slot.purchase_display == "—"
    assert slot.stock_display == "—"


def test_build_planogram_slot_stock_overflow_flag() -> None:
    slot = _planogram_slot_with_chips(
        line_number="11",
        product_code="A",
        stock_qty=Decimal("4"),
        capacity=3,
        purchase=Decimal("10"),
        calculated="113",
        current="113",
    )
    assert slot.stock_overflow is True


def test_build_planogram_slot_price_diff_flag() -> None:
    slot = _planogram_slot_with_chips(
        line_number="11",
        product_code="A",
        stock_qty=Decimal("1"),
        capacity=10,
        purchase=Decimal("10"),
        calculated="113",
        current="112",
    )
    assert slot.price_diff is True


def test_capacity_display_empty_product() -> None:
    assert capacity_display_for(product_code="", catalog_capacity=12) == ""


def test_capacity_display_missing_catalog() -> None:
    assert capacity_display_for(product_code="1616", catalog_capacity=None) == "—"


def test_capacity_display_zero() -> None:
    assert capacity_display_for(product_code="1616", catalog_capacity=0) == "0"


def test_build_product_options_prefers_catalog_display_name() -> None:
    opts = build_layout_product_options(
        known_codes=frozenset({"1616", "999"}),
        ms_names={"1616": "MS Чудо", "999": "MS Other"},
        catalog_by_code={"1616": ("Чудо Йогурт", 12)},
    )
    by_code = {o.product_code: o for o in opts}
    assert by_code["1616"].display_name == "Чудо Йогурт"
    assert by_code["1616"].capacity_display == "12"
    assert by_code["999"].display_name == "MS Other"
    assert by_code["999"].capacity_display == "—"


def _opts() -> dict[str, LayoutProductOption]:
    return {
        "1616": LayoutProductOption("1616", "Чудо", "12"),
        "2000": LayoutProductOption("2000", "Чудо", "5"),
        "3000": LayoutProductOption("3000", "Уникальный", "1"),
    }


def _names() -> dict[str, frozenset[str]]:
    return {
        "чудо": frozenset({"1616", "2000"}),
        "уникальный": frozenset({"3000"}),
    }


def test_parse_planogram_form_omits_empty_anchor() -> None:
    parsed = parse_planogram_form(
        shelf_count_raw="6",
        slots_per_shelf_raw="10",
        shelf_indices=["0"],
        slot_indices=["0"],
        line_numbers=[""],
        product_codes=[""],
        product_names=[""],
        merge_shelves=[],
        merge_slots=[],
        options_by_code=_opts(),
        name_to_codes=_names(),
    )
    assert parsed.anchors == ()


def test_parse_planogram_form_prefers_hidden_code() -> None:
    parsed = parse_planogram_form(
        shelf_count_raw="6",
        slots_per_shelf_raw="10",
        shelf_indices=["0"],
        slot_indices=["1"],
        line_numbers=["5"],
        product_codes=["1616"],
        product_names=["неважно"],
        merge_shelves=[],
        merge_slots=[],
        options_by_code=_opts(),
        name_to_codes=_names(),
    )
    assert len(parsed.anchors) == 1
    assert parsed.anchors[0].line_number == 5
    assert parsed.anchors[0].product_code == "1616"


def test_parse_planogram_form_resolves_unique_name() -> None:
    parsed = parse_planogram_form(
        shelf_count_raw="6",
        slots_per_shelf_raw="10",
        shelf_indices=["0"],
        slot_indices=["2"],
        line_numbers=["3"],
        product_codes=[""],
        product_names=["Уникальный"],
        merge_shelves=[],
        merge_slots=[],
        options_by_code=_opts(),
        name_to_codes=_names(),
    )
    assert parsed.anchors[0].product_code == "3000"


def test_parse_planogram_form_rejects_ambiguous_name() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0"],
            slot_indices=["0"],
            line_numbers=["1"],
            product_codes=[""],
            product_names=["Чудо"],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "ambiguous_product_name"


def test_parse_planogram_form_rejects_unknown_name() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0"],
            slot_indices=["0"],
            line_numbers=["1"],
            product_codes=[""],
            product_names=["НетТакого"],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "unknown_product_name"


def test_parse_planogram_form_rejects_invalid_line_number() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0"],
            slot_indices=["0"],
            line_numbers=["0"],
            product_codes=["1616"],
            product_names=["Чудо"],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "invalid_line_number"


def test_parse_planogram_form_rejects_unknown_code() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0"],
            slot_indices=["0"],
            line_numbers=["1"],
            product_codes=["NOPE"],
            product_names=[""],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "unknown_product_code"


def test_parse_planogram_form_rejects_duplicate_line() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0", "1"],
            slot_indices=["0", "0"],
            line_numbers=["11", "11"],
            product_codes=["1616", "3000"],
            product_names=["", ""],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "duplicate_line_number"


def test_parse_planogram_form_rejects_unequal_array_lengths() -> None:
    with pytest.raises(LayoutFormParseError) as exc:
        parse_planogram_form(
            shelf_count_raw="6",
            slots_per_shelf_raw="10",
            shelf_indices=["0"],
            slot_indices=["0", "1"],
            line_numbers=["1"],
            product_codes=["1616"],
            product_names=["Чудо"],
            merge_shelves=[],
            merge_slots=[],
            options_by_code=_opts(),
            name_to_codes=_names(),
        )
    assert exc.value.code == "invalid_layout_form"


def test_layout_product_options_json_escapes_script_breakout() -> None:
    options = (
        LayoutProductOption(
            product_code="1616",
            display_name="</script><img src=x>",
            capacity_display="12",
        ),
    )
    raw = layout_product_options_json(options)
    assert "</script>" not in raw
    payload = json.loads(raw)
    assert payload["1616"]["name"] == "</script><img src=x>"


def _machine() -> MasterMachine:
    return MasterMachine(
        machine_id=MachineId("514"),
        kind=MachineKind.SNACK,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )


def _snack_machine(machine_id: str) -> MasterMachine:
    return MasterMachine(
        machine_id=MachineId(machine_id),
        kind=MachineKind.SNACK,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
    )


def _empty_machine_store() -> MasterMachineStore:
    return InMemoryMasterDataStores().machines


def test_build_planogram_view_from_submitted_fields_preserves_invalid_line() -> None:
    options = (LayoutProductOption("NEW", "New Product", "5"),)
    view = build_planogram_view_from_submitted_fields(
        machine=_snack_machine("512"),
        machines=_empty_machine_store(),
        shelf_count_raw="6",
        slots_per_shelf_raw="10",
        shelf_indices=["0", "0"],
        slot_indices=["0", "7"],
        line_numbers=["0", "8"],
        product_codes=["NEW", "NEW"],
        product_names=["New Product", "New Product"],
        merge_shelves=[],
        merge_slots=[],
        matrix_multiplier_raw="1",
        auto_sync_enabled=False,
        product_options=options,
    )
    by_slot = {(s.shelf_index, s.slot_index): s for s in view.slots}
    assert by_slot[(0, 0)].line_number == "0"
    assert by_slot[(0, 7)].line_number == "8"
    assert "New Product" in by_slot[(0, 7)].product_name


def _layout_store() -> InMemorySnackMachineLayoutStore:
    store = InMemorySnackMachineLayoutStore()
    store.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="514",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(SnackMachineLayoutCell(1, "SKU1"),),
        )
    )
    return store


def test_layout_calculated_price_when_inputs_present() -> None:
    params = curved_margin_params()
    purchase = Decimal("50")
    expected = str(
        calculate_sell_price(
            purchase=purchase,
            product_multiplier=Decimal("1"),
            matrix_multiplier=Decimal("1"),
            params=params,
        )
    )
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(_machine())
    view = build_snack_layout_profile_view(
        machine=_machine(),
        layout_store=_layout_store(),
        machines=machines.machines,
        base_margin=params,
        purchases={"SKU1": purchase},
        product_multipliers={"SKU1": Decimal("1")},
    )
    assert view is not None
    slot = next(s for s in view.slots if s.product_code == "SKU1")
    assert slot.calculated_display == expected


def test_layout_calculated_dash_without_purchase() -> None:
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(_machine())
    view = build_snack_layout_profile_view(
        machine=_machine(),
        layout_store=_layout_store(),
        machines=machines.machines,
        base_margin=curved_margin_params(),
        purchases={},
        product_multipliers={"SKU1": Decimal("1")},
    )
    assert view is not None
    slot = next(s for s in view.slots if s.product_code == "SKU1")
    assert slot.calculated_display == "—"


def test_layout_calculated_dash_on_ms_fail() -> None:
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(_machine())
    view = build_snack_layout_profile_view(
        machine=_machine(),
        layout_store=_layout_store(),
        machines=machines.machines,
        base_margin=curved_margin_params(),
        purchases=None,
        product_multipliers={"SKU1": Decimal("1")},
    )
    assert view is not None
    assert all(s.calculated_display == "—" for s in view.slots if s.product_code)


def test_layout_calculated_dash_without_base_margin() -> None:
    machines = InMemoryMasterDataStores()
    machines.machines.upsert(_machine())
    view = build_snack_layout_profile_view(
        machine=_machine(),
        layout_store=_layout_store(),
        machines=machines.machines,
        base_margin=None,
        purchases={"SKU1": Decimal("50")},
        product_multipliers={"SKU1": Decimal("1")},
    )
    assert view is not None
    slot = next(s for s in view.slots if s.product_code == "SKU1")
    assert slot.calculated_display == "—"


def _slot_for_cell(
    cell: SnackMachineLayoutCell,
    *,
    product_name: str = "",
    linked: bool = True,
) -> PlanogramSlotView:
    products = MemoryDomainProductStore()
    domain_id = (cell.domain_product_id or "").strip()
    if domain_id and product_name:
        products.insert(
            DomainProduct(
                domain_product_id=domain_id,
                number="d-1",
                name=product_name,
                catalog_code="2311" if linked else None,
                hidden=False,
            )
        )
    anchored = cell
    if cell.shelf_index is None or cell.slot_index is None:
        anchored = SnackMachineLayoutCell(
            cell.line_number,
            cell.product_code,
            0,
            0,
            domain_product_id=cell.domain_product_id,
        )
    slots = build_planogram_slots(
        shelf_count=1,
        slots_per_shelf=1,
        merges=(),
        cells=(anchored,),
        options_by_code={},
        products=products,
    )
    return slots[0]


def test_snack_slot_unlinked_product_has_empty_chips_and_link_fields() -> None:
    slot = _slot_for_cell(
        SnackMachineLayoutCell(1, None, domain_product_id="prod-1"),
        product_name="Кефир",
        linked=False,
    )
    assert slot.domain_product_id == "prod-1"
    assert slot.product_name == "Кефир"
    assert slot.unlinked is True
    assert slot.capacity_display in {"", "—"}
    assert slot.calculated_display in {"", "—"}
    assert slot.product_code == ""


def test_snack_slot_missing_product_keeps_id() -> None:
    slot = _slot_for_cell(
        SnackMachineLayoutCell(1, None, domain_product_id="missing"),
        product_name="",
        linked=False,
    )
    assert slot.domain_product_id == "missing"
    assert slot.unlinked is True
    assert slot.product_name == "Товар не найден"
