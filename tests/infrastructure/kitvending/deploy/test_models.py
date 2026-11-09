from __future__ import annotations

from decimal import Decimal

from src.infrastructure.kitvending.deploy.models import (
    KIT_GOODS_NAME_MAX_LENGTH,
    KitMatrixCommandCode,
    KitMatrixPosition,
    build_matrix_position,
    format_kit_goods_name,
)


def test_command_codes_match_kit_contract() -> None:
    assert KitMatrixCommandCode.LOAD_MATRIX == 3
    assert KitMatrixCommandCode.APPLY_MATRIX == 4


def test_format_kit_goods_name_prefixes_code() -> None:
    """happy: `{code} | {name}` без truncate."""
    assert format_kit_goods_name("2312", "Кола") == "2312 | Кола"


def test_format_kit_goods_name_truncates_to_max_length() -> None:
    """edge: длинное имя → len == KIT_GOODS_NAME_MAX_LENGTH, suffix `...`, код в начале."""
    long_name = "X" * 80
    result = format_kit_goods_name("2312", long_name)
    assert len(result) == KIT_GOODS_NAME_MAX_LENGTH
    assert result.endswith("...")
    assert result.startswith("2312 | ")
    assert KIT_GOODS_NAME_MAX_LENGTH == 64


def test_normal_line_maps_to_position_price_fields() -> None:
    """regress: GoodsName через format_kit_goods_name."""
    position = build_matrix_position(
        line_number=1,
        product_name="Кола",
        product_code="MS-1",
        deploy_price=Decimal("120"),
        capacity=10,
        blocking_label="БЛОК",
    )
    assert position == KitMatrixPosition(
        line_number=1,
        goods_name="MS-1 | Кола",
        price="120",
        price2="120",
        max_count=10,
    )


def test_blocked_empty_line_maps_to_blocking_cell() -> None:
    position = build_matrix_position(
        line_number=2,
        product_name="",
        product_code=None,
        deploy_price=Decimal("999"),
        capacity=12,
        blocking_label=" БЛОК ",
    )
    assert position.goods_name == "БЛОК"
    assert position.price == "999"
    assert position.price2 == "999"
    assert position.max_count == 0
