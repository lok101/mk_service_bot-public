from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.matrix_automation import PlanogramAnchorCell, SnackPlanogramMerge
from src.interfaces.admin.machine_layout_render import LayoutProductOption


@beartype
@dataclass(frozen=True, slots=True)
class ParsedPlanogramForm:
    shelf_count: int
    slots_per_shelf: int
    merges: tuple[SnackPlanogramMerge, ...]
    anchors: tuple[PlanogramAnchorCell, ...]


class LayoutFormParseError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
def parse_positive_int(raw: str, *, field_name: str) -> int:
    text = raw.strip()
    if not text.isdigit() or int(text) < 1:
        raise LayoutFormParseError(
            f"{field_name} must be a positive integer",
            code="invalid_planogram_dimensions",
        )
    return int(text)


@beartype
def parse_planogram_form(
    *,
    shelf_count_raw: str,
    slots_per_shelf_raw: str,
    shelf_indices: Sequence[str],
    slot_indices: Sequence[str],
    line_numbers: Sequence[str],
    product_codes: Sequence[str],
    product_names: Sequence[str],
    merge_shelves: Sequence[str],
    merge_slots: Sequence[str],
    options_by_code: Mapping[str, LayoutProductOption],
    name_to_codes: Mapping[str, frozenset[str]],
    domain_product_ids: Sequence[str] | None = None,
) -> ParsedPlanogramForm:
    """Parse parallel anchor fields + planogram dimensions + merges."""
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

    anchors: list[PlanogramAnchorCell] = []
    seen_lines: set[int] = set()
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
            raise LayoutFormParseError(
                "anchor shelf/slot must be non-negative integers",
                code="invalid_layout_form",
            )
        shelf_index = int(shelf_raw.strip())
        slot_index = int(slot_raw.strip())
        line_text = line_raw.strip()
        if not line_text or not line_text.isdigit() or int(line_text) < 1:
            raise LayoutFormParseError(
                "line_number must be an integer >= 1",
                code="invalid_line_number",
            )
        line = int(line_text)
        if line in seen_lines:
            raise LayoutFormParseError(
                f"duplicate line_number: {line}",
                code="duplicate_line_number",
            )
        seen_lines.add(line)
        if domain_id:
            anchors.append(
                PlanogramAnchorCell(
                    shelf_index=shelf_index,
                    slot_index=slot_index,
                    line_number=line,
                    product_code=None,
                    domain_product_id=domain_id,
                )
            )
            continue
        if code:
            if code not in options_by_code:
                raise LayoutFormParseError(
                    f"unknown product_code: {code}",
                    code="unknown_product_code",
                )
            resolved_code = code
        else:
            key = name.casefold()
            codes = name_to_codes.get(key, frozenset())
            if len(codes) == 0:
                raise LayoutFormParseError(
                    f"unknown product name: {name}",
                    code="unknown_product_name",
                )
            if len(codes) > 1:
                raise LayoutFormParseError(
                    f"ambiguous product name: {name}",
                    code="ambiguous_product_name",
                )
            resolved_code = next(iter(codes))
        anchors.append(
            PlanogramAnchorCell(
                shelf_index=shelf_index,
                slot_index=slot_index,
                line_number=line,
                product_code=resolved_code,
            )
        )

    return ParsedPlanogramForm(
        shelf_count=shelf_count,
        slots_per_shelf=slots_per_shelf,
        merges=tuple(merges),
        anchors=tuple(anchors),
    )
