from __future__ import annotations

from src.interfaces.admin.machine_layout_parse import (
    LayoutFormParseError,
    ParsedPlanogramForm,
    parse_planogram_form,
)
from src.interfaces.admin.machine_layout_post import (
    build_planogram_view_from_submitted_fields,
    build_save_snack_layout_input_from_parsed_planogram,
    build_snack_planogram_profile_view_from_submitted_fields,
    layout_section_visible,
    merge_domain_product_slot_fields,
)
from src.interfaces.admin.machine_layout_render import (
    LayoutProductOption,
    PlanogramSlotView,
    SnackPlanogramProfileView,
    _planogram_slot_with_chips,
    build_layout_product_options,
    build_planogram_slots,
    build_snack_layout_profile_view,
    capacity_display_for,
    layout_product_options_json,
    name_index_from_options,
)

__all__ = [
    "LayoutFormParseError",
    "LayoutProductOption",
    "ParsedPlanogramForm",
    "PlanogramSlotView",
    "SnackPlanogramProfileView",
    "_planogram_slot_with_chips",
    "build_layout_product_options",
    "build_planogram_slots",
    "build_planogram_view_from_submitted_fields",
    "build_save_snack_layout_input_from_parsed_planogram",
    "build_snack_layout_profile_view",
    "build_snack_planogram_profile_view_from_submitted_fields",
    "capacity_display_for",
    "layout_product_options_json",
    "layout_section_visible",
    "merge_domain_product_slot_fields",
    "name_index_from_options",
    "parse_planogram_form",
]
