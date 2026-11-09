from __future__ import annotations

from uuid import UUID

from beartype import beartype

from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError
from src.infrastructure.integrations.moysklad.http import MoySkladHttpTransport


@beartype
async def get_store_id_by_code(http: MoySkladHttpTransport, warehouse_code: str) -> UUID:
    if not warehouse_code:
        raise MoySkladValidationError("Код склада обязателен для создания инвентаризации.")
    response = await http.get(
        "/entity/store",
        params={"filter": f"code={warehouse_code}", "limit": 2},
    )
    rows = response.get("rows") if isinstance(response, dict) else None
    if not isinstance(rows, list) or not rows:
        raise MoySkladValidationError(f"Склад с кодом '{warehouse_code}' не найден.")
    if len(rows) > 1:
        raise MoySkladValidationError(f"Найдено несколько складов с кодом '{warehouse_code}'.")
    return UUID(str(rows[0]["id"]))
