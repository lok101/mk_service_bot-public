from __future__ import annotations

from beartype import beartype


@beartype
def build_kitshop_sale_source_id(*, sale_id: int, position_id: int) -> str:
    return f"kitshop:{sale_id}:{position_id}"
