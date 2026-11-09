from __future__ import annotations

import logging

import pytest

from src.infrastructure.integrations.kitvending.api_models.matrix import (
    ComboMatrixModel,
    GoodsMatrixModel,
    RecipeMatrixModel,
)
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel
from src.infrastructure.integrations.kitvending.parsing.exceptions import (
    SaleProductCodeResolveCriticalError,
    SaleProductCodeResolveNonCriticalError,
)
from src.infrastructure.integrations.kitvending.parsing.sale_resolve import (
    resolve_sale_product_code,
    resolve_sale_vending_machine_code,
    resolve_sales_with_catalog,
)


def _sale(
    *,
    goods_name: str,
    matrix_id: int | None,
    line: int = 1,
    vending_machine_name: str = "Test [501]",
) -> SaleModel:
    return SaleModel.model_validate(
        {
            "LineNumber": line,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": goods_name,
            "VendingMachine": 1,
            "VendingMachineName": vending_machine_name,
            "MatrixId": matrix_id,
        }
    )


def test_human_name_resolves_via_vm_current_matrix() -> None:
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Snack",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 3,
                    "Price2": 10.0,
                    "GoodsName": "2101 | Snack",
                    "MaxCount": 5,
                }
            ],
        }
    )
    sale = _sale(goods_name="Капучино классический", matrix_id=999, line=3)
    assert (
        resolve_sale_product_code(
            sale,
            {10: matrix},
            {},
            matrix_id_by_vm_id={1: 10},
        )
        == "2101"
    )


def test_pipe_code_ignores_vm_index() -> None:
    sale = _sale(goods_name="2312 | Name", matrix_id=None)
    assert resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={}) == "2312"


def test_line_minus_one_non_critical_unchanged() -> None:
    sale = _sale(goods_name="Капучино", matrix_id=None, line=-1)
    with pytest.raises(SaleProductCodeResolveNonCriticalError):
        resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={1: 10})


def test_product_zero_non_critical_unchanged() -> None:
    sale = _sale(goods_name="Товар 0", matrix_id=None)
    with pytest.raises(SaleProductCodeResolveNonCriticalError):
        resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={1: 10})


def test_placeholder_tovar_n_via_vm_current_matrix() -> None:
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Snack",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 1,
                    "Price2": 10.0,
                    "GoodsName": "2101 | Snack",
                    "MaxCount": 5,
                }
            ],
        }
    )
    sale = _sale(goods_name="Товар 12", matrix_id=None, line=1)
    assert (
        resolve_sale_product_code(
            sale,
            {10: matrix},
            {},
            matrix_id_by_vm_id={1: 10},
        )
        == "2101"
    )


def test_tcn_even_line_uses_line_minus_one_cell() -> None:
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Snack",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 3,
                    "Price2": 10.0,
                    "GoodsName": "2101 | Snack",
                    "MaxCount": 5,
                }
            ],
        }
    )
    sale = _sale(goods_name="Напиток", matrix_id=None, line=4)
    assert (
        resolve_sale_product_code(
            sale,
            {10: matrix},
            {},
            matrix_id_by_vm_id={1: 10},
        )
        == "2101"
    )


def test_even_line_prefers_exact_cell_over_tcn_neighbor() -> None:
    """Coffee: lines 5 and 6 both present; even sale must not steal line-1 via TCN."""
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Coffee",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 5,
                    "Price2": 109.0,
                    "GoodsName": "108 | Мокко 250мл Bluetec",
                    "MaxCount": 1,
                },
                {
                    "LineNumber": 6,
                    "Price2": 109.0,
                    "GoodsName": "107 | Капучино 250мл Bluetec",
                    "MaxCount": 1,
                },
            ],
        }
    )
    sale = _sale(goods_name="Товар 6", matrix_id=None, line=6)
    assert (
        resolve_sale_product_code(
            sale,
            {10: matrix},
            {},
            matrix_id_by_vm_id={1: 10},
        )
        == "107"
    )


def test_placeholder_2xxx_fallback_without_vm_matrix() -> None:
    sale = _sale(goods_name="Товар 2311", matrix_id=None)
    assert resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={}) == "2311"


def test_human_name_without_vm_matrix_raises_critical() -> None:
    sale = _sale(goods_name="Капучино классический", matrix_id=None)
    with pytest.raises(SaleProductCodeResolveCriticalError, match="текущ"):
        resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={})


def test_matrix_missing_in_catalog_not_2xxx_raises_critical() -> None:
    sale = _sale(goods_name="Капучино", matrix_id=None)
    with pytest.raises(SaleProductCodeResolveCriticalError, match="не найдена"):
        resolve_sale_product_code(
            sale,
            {},
            {},
            matrix_id_by_vm_id={1: 999},
        )


def test_combo_via_vm_index_raises_critical() -> None:
    matrix = ComboMatrixModel.model_validate(
        {"MatrixId": 30, "MatrixName": "Combo", "MatrixType": 3, "Details": []},
    )
    sale = _sale(goods_name="Товар 2311", matrix_id=None, line=1)
    with pytest.raises(SaleProductCodeResolveCriticalError, match="Combo"):
        resolve_sale_product_code(
            sale,
            {30: matrix},
            {},
            matrix_id_by_vm_id={1: 30},
        )


def test_recipe_without_code_raises_critical() -> None:
    matrix = RecipeMatrixModel.model_validate(
        {
            "MatrixId": 20,
            "MatrixName": "Coffee",
            "MatrixType": 2,
            "Details": [{"LineNumber": 1, "Price2": 50.0, "FormulationId": 7}],
        }
    )
    recipe = RecipeModel.model_validate(
        {"FormulationId": 7, "FormulationName": "Latte без кода"},
    )
    sale = _sale(goods_name="Латте", matrix_id=None, line=1)
    with pytest.raises(SaleProductCodeResolveCriticalError, match="кода"):
        resolve_sale_product_code(
            sale,
            {20: matrix},
            {7: recipe},
            matrix_id_by_vm_id={1: 20},
        )


def test_matrix_id_none_four_digit_two() -> None:
    sale = _sale(goods_name="Товар 2311", matrix_id=None)
    assert resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={}) == "2311"


def test_matrix_id_none_no_fallback() -> None:
    sale = _sale(goods_name="Товар 12", matrix_id=None)
    with pytest.raises(SaleProductCodeResolveCriticalError):
        resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={})


def test_matrix_missing_in_catalog_four_digit_two() -> None:
    sale = _sale(goods_name="Товар 2101", matrix_id=999)
    assert resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={1: 999}) == "2101"


def test_matrix_missing_no_fallback_wrong_prefix() -> None:
    sale = _sale(goods_name="Товар 3999", matrix_id=None)
    with pytest.raises(SaleProductCodeResolveCriticalError):
        resolve_sale_product_code(sale, {}, {}, matrix_id_by_vm_id={})


def test_inactive_machine_name_still_resolves_code() -> None:
    """D1: [ X ] не блокирует resolve кода аппарата в sale_resolve (фильтра нет)."""
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | X",
            "VendingMachine": 1,
            "VendingMachineName": "Кофе [129] [ X ]",
            "MatrixId": None,
        }
    )
    assert resolve_sale_vending_machine_code(sale) == "129"


def test_resolve_product_code_from_goods_matrix_cell() -> None:
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Snack",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 3,
                    "Price2": 10.0,
                    "GoodsName": "2101 | Snack",
                    "MaxCount": 5,
                }
            ],
        }
    )
    sale = _sale(goods_name="Товар 2101", matrix_id=10, line=3)
    assert resolve_sale_product_code(sale, {10: matrix}, {}, matrix_id_by_vm_id={1: 10}) == "2101"


def test_resolve_product_code_from_recipe_matrix() -> None:
    matrix = RecipeMatrixModel.model_validate(
        {
            "MatrixId": 20,
            "MatrixName": "Coffee",
            "MatrixType": 2,
            "Details": [{"LineNumber": 1, "Price2": 50.0, "FormulationId": 7}],
        }
    )
    recipe = RecipeModel.model_validate(
        {"FormulationId": 7, "FormulationName": "2301 | Latte"},
    )
    sale = _sale(goods_name="Товар 2301", matrix_id=20, line=1)
    assert (
        resolve_sale_product_code(sale, {20: matrix}, {7: recipe}, matrix_id_by_vm_id={1: 20})
        == "2301"
    )


def test_combo_matrix_raises_critical() -> None:
    matrix = ComboMatrixModel.model_validate(
        {"MatrixId": 30, "MatrixName": "Combo", "MatrixType": 3, "Details": []},
    )
    sale = _sale(goods_name="Товар 2311", matrix_id=30, line=1)
    with pytest.raises(SaleProductCodeResolveCriticalError, match="Combo"):
        resolve_sale_product_code(sale, {30: matrix}, {}, matrix_id_by_vm_id={1: 30})


def test_resolve_sales_with_catalog_skips_missing_machine_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    ok = _sale(goods_name="2312 | X", matrix_id=None, vending_machine_name="[129]")
    bad_vm = _sale(goods_name="2312 | X", matrix_id=None, vending_machine_name="без кода")
    resolved = resolve_sales_with_catalog([ok, bad_vm], {}, {}, matrix_id_by_vm_id={})
    assert len(resolved) == 1
    assert resolved[0].vending_machine_code == "129"
    assert any("код аппарата" in r.message for r in caplog.records)
