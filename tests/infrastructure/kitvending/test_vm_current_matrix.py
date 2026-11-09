from __future__ import annotations

import pytest

from src.infrastructure.integrations.kitvending.vm_current_matrix import (
    normalize_goods_matrix_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (42, 42),
        (" 77 ", 77),
        ({"Id": 10}, 10),
        ({"MatrixId": 11}, 11),
        ({"Id": "12"}, 12),
        ({"MatrixId": "13"}, 13),
        (None, None),
        (0, None),
        ("0", None),
        ("", None),
        ("  ", None),
        ("abc", None),
        ({}, None),
        ({"Id": 0}, None),
        ({"MatrixId": None}, None),
        ({"Name": "x"}, None),
        ([], None),
    ],
)
def test_normalize_goods_matrix_id_branches(raw: object, expected: int | None) -> None:
    assert normalize_goods_matrix_id(raw) == expected


def test_normalize_prefers_id_over_matrix_id_when_both_present() -> None:
    assert normalize_goods_matrix_id({"Id": 1, "MatrixId": 2}) == 1
