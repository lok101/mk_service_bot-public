from __future__ import annotations

from typing import Any

from beartype import beartype


@beartype
def normalize_goods_matrix_id(value: object) -> int | None:
    """GoodsMatrix → matrix_id > 0, иначе None (см. spec vm_current_matrix)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = int(stripped)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    if isinstance(value, dict):
        raw: Any
        if "Id" in value:
            raw = value["Id"]
        elif "MatrixId" in value:
            raw = value["MatrixId"]
        else:
            return None
        return normalize_goods_matrix_id(raw)
    return None
