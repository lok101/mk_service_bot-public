from __future__ import annotations

from src.application.inventory_reconciliation.kitshop_source_id import (
    build_kitshop_sale_source_id,
)


def test_kitshop_source_id_per_position() -> None:
    assert build_kitshop_sale_source_id(sale_id=100, position_id=1) == "kitshop:100:1"
    assert build_kitshop_sale_source_id(sale_id=100, position_id=2) == "kitshop:100:2"
    assert build_kitshop_sale_source_id(sale_id=100, position_id=1) != (
        build_kitshop_sale_source_id(sale_id=100, position_id=2)
    )
