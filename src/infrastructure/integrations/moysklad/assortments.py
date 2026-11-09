from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from beartype import beartype

from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport

AssortmentEntityType = Literal["product", "variant", "bundle"]


@beartype
@dataclass(frozen=True, slots=True)
class AssortmentRef:
    id: UUID
    entity_type: AssortmentEntityType


@beartype
async def resolve_assortments_by_codes(
    http: MoySkladHttpTransport,
    product_codes: list[str],
) -> dict[str, AssortmentRef]:
    """Resolve assortment refs by product ``code`` via 3 batch entity lists.

    Not N+1. Watch filter URL length if ``product_codes`` grows very large.
    """
    unique_codes = list(dict.fromkeys(product_codes))
    if any(not code for code in unique_codes):
        raise MoySkladValidationError("Код товара в позиции инвентаризации не может быть пустым.")
    if not unique_codes:
        raise MoySkladValidationError("Список позиций инвентаризации не может быть пустым.")

    filter_value = ";".join(f"code={code}" for code in unique_codes)
    requested = set(unique_codes)
    matches: dict[str, list[AssortmentRef]] = defaultdict(list)

    entity_types: tuple[tuple[str, AssortmentEntityType], ...] = (
        ("product", "product"),
        ("variant", "variant"),
        ("bundle", "bundle"),
    )
    for entity_path, entity_type in entity_types:
        response = await http.get(
            f"/entity/{entity_path}",
            params={"filter": filter_value, "limit": len(unique_codes)},
        )
        rows = response.get("rows") if isinstance(response, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            row_id = row.get("id")
            if isinstance(code, str) and code in requested and row_id is not None:
                matches[code].append(AssortmentRef(id=UUID(str(row_id)), entity_type=entity_type))

    missing = [code for code in unique_codes if code not in matches]
    if missing:
        raise MoySkladValidationError(f"Не найдены товары для кодов: {', '.join(missing)}.")

    duplicates = [code for code in unique_codes if len(matches[code]) > 1]
    if duplicates:
        joined = ", ".join(duplicates)
        raise MoySkladValidationError(f"Найдено несколько товаров для кодов: {joined}.")

    return {code: matches[code][0] for code in unique_codes}
