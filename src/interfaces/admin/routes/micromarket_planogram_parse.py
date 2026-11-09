from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from beartype import beartype

from src.application.micromarket_loading import (
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.shared import parse_sheet_decimal

_INDEXED_FIELD = re.compile(
    r"^(domain_product_id|product_code|target_qty|price_rub|active|pending_exit)-(\d+)$"
)

_SHELF_FIELD = re.compile(r"^shelf_kit_group_id-(\d+)$")


@beartype
def _planogram_save_status(message: str) -> int:
    lowered = message.casefold()
    if "unknown" in lowered:
        return 422
    if "не на полке" in lowered:
        return 422
    if "две полки с одной группой kit" in lowered:
        return 422
    if "некорректная полка" in lowered:
        return 422
    if "цен" in lowered or "price_rub" in lowered:
        return 400
    return 400


@beartype
def _format_price_rub_ui(price: Decimal) -> str:
    integral = price.to_integral_value()
    if price == integral:
        return format(integral, "f").split(".", 1)[0]
    text = format(price, "f").rstrip("0").rstrip(".")
    return text


@beartype
def _parse_shelves(parsed: Mapping[str, list[str]]) -> tuple[MicromarketPlanogramShelf, ...]:
    indices: set[int] = set()
    for key in parsed:
        match = _SHELF_FIELD.match(key)
        if match is not None:
            indices.add(int(match.group(1)))
    shelves: list[MicromarketPlanogramShelf] = []
    seen_ids: set[int] = set()
    for index in sorted(indices):
        raw = (parsed.get(f"shelf_kit_group_id-{index}") or [""])[-1].strip()
        try:
            kit_group_id = int(raw)
        except ValueError as exc:
            raise ValueError("Некорректная полка") from exc
        if kit_group_id <= 0:
            raise ValueError("Некорректная полка")
        if kit_group_id in seen_ids:
            raise ValueError("Две полки с одной группой Kit")
        seen_ids.add(kit_group_id)
        shelves.append(
            MicromarketPlanogramShelf(kit_group_id=kit_group_id, sort_order=len(shelves))
        )
    return tuple(shelves)


@beartype
def _parse_planogram_form(
    parsed: Mapping[str, list[str]],
) -> tuple[tuple[MicromarketPlanogramShelf, ...], list[MicromarketPlanogramLine]]:
    shelves = _parse_shelves(parsed)
    indices: set[int] = set()
    for key in parsed:
        match = _INDEXED_FIELD.match(key)
        if match is not None:
            indices.add(int(match.group(2)))
    lines: list[MicromarketPlanogramLine] = []
    for index in sorted(indices):
        domain_id = (parsed.get(f"domain_product_id-{index}") or [""])[-1].strip()
        code = (parsed.get(f"product_code-{index}") or [""])[-1].strip()
        if domain_id:
            code = ""
        elif not code:
            continue
        target_raw = (parsed.get(f"target_qty-{index}") or ["0"])[-1].strip() or "0"
        price_raw = (parsed.get(f"price_rub-{index}") or [""])[-1].strip()
        if not price_raw:
            raise ValueError(f"Укажите цену для строки {index}")
        # Active column removed from UI; always persist active=true on Save.
        active = True
        pending_exit = (
            f"pending_exit-{index}" in parsed
            and (parsed.get(f"pending_exit-{index}") or [""])[-1] != ""
        )
        try:
            target_qty = int(target_raw)
            price_rub = parse_sheet_decimal(price_raw)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"invalid target_qty or price_rub at row {index}") from exc
        if price_rub != price_rub.to_integral_value():
            raise ValueError(f"Цена должна быть целым числом рублей (строка {index})")
        if price_rub < 1:
            raise ValueError(f"Цена должна быть не меньше 1 ₽ (строка {index})")
        price_rub = price_rub.to_integral_value()
        kit_group_raw = (parsed.get(f"kit_group_id-{index}") or [""])[-1].strip()
        if kit_group_raw == "":
            kit_group_id: int | None = None
        else:
            try:
                kit_group_id = int(kit_group_raw)
            except ValueError as exc:
                raise ValueError(f"invalid kit_group_id at row {index}") from exc
        lines.append(
            MicromarketPlanogramLine(
                product_code=code,
                target_qty=target_qty,
                price_rub=price_rub,
                active=active,
                sort_order=len(lines),
                kit_group_id=kit_group_id,
                domain_product_id=domain_id or None,
                pending_exit=pending_exit,
            ),
        )
    return shelves, lines


@beartype
def _submitted_form_best_effort(
    parsed: Mapping[str, list[str]],
) -> tuple[
    tuple[MicromarketPlanogramShelf, ...] | None,
    list[MicromarketPlanogramLine] | None,
]:
    try:
        shelves, lines = _parse_planogram_form(parsed)
        return shelves, lines
    except ValueError:
        # Incomplete rows (e.g. missing price) cannot rebuild product lines.
        # Returning empty lines with submitted shelves blanks the UI (LOK-293);
        # None/None re-renders the stored document as a valid snapshot.
        return None, None
