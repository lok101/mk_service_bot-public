"""Разрешение продаж Kit в код товара и SaleResolvedModel."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from beartype import beartype

from src.application.matrix_automation import extract_vending_machine_code
from src.infrastructure.integrations.kitvending.api_models.matrix import (
    ComboMatrixModel,
    GoodsCell,
    GoodsMatrixModel,
    MatrixModel,
    RecipeCell,
    RecipeMatrixModel,
)
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel, SaleResolvedModel
from src.infrastructure.integrations.kitvending.parsing.exceptions import (
    SaleProductCodeResolveCriticalError,
    SaleProductCodeResolveNonCriticalError,
)
from src.infrastructure.integrations.kitvending.parsing.utils import (
    compute_vending_machine_type,
    is_product_zero_placeholder,
    try_product_code_from_placeholder_name,
)

_LOGGER: Final = logging.getLogger(__name__)


@beartype
def resolve_sale_vending_machine_code(sale: SaleModel) -> str | None:
    vending_machine_code: str | None = extract_vending_machine_code(sale.vending_machine_name)
    if vending_machine_code is None:
        return None
    return vending_machine_code


def _resolve_matrix_cell(matrix: MatrixModel, line: int) -> GoodsCell | RecipeCell | None:
    """Exact LineNumber first; TCN even→line-1 only when exact cell is absent."""
    exact: GoodsCell | RecipeCell | None = None
    tcn_fallback: GoodsCell | RecipeCell | None = None
    for c in matrix.cells:
        if not isinstance(c, (GoodsCell, RecipeCell)):
            continue
        if c.line_number == line:
            exact = c
            break
        if line % 2 == 0 and c.line_number == line - 1:
            tcn_fallback = c
    return exact if exact is not None else tcn_fallback


@beartype
def resolve_sale_product_code(
    sale: SaleModel,
    matrices_by_id: dict[int, MatrixModel],
    recipes_by_id: dict[int, RecipeModel],
    matrix_id_by_vm_id: Mapping[int, int],
) -> str:
    """Возвращает код товара или бросает SaleProductCodeResolve*Error."""
    direct = sale.product_code
    if direct is not None:
        return direct

    if sale.line == -1:
        raise SaleProductCodeResolveNonCriticalError(
            "продажа помечена как «переплата» (LineNumber=-1)"
        )

    if is_product_zero_placeholder(sale.product_name):
        raise SaleProductCodeResolveNonCriticalError("плейсхолдер «Товар 0» — недопустимая позиция")

    matrix_id = matrix_id_by_vm_id.get(sale.vending_machine_id)
    matrix = matrices_by_id.get(matrix_id) if matrix_id is not None else None

    if matrix is None:
        fallback = try_product_code_from_placeholder_name(sale.product_name)
        if fallback is not None:
            return fallback
        if matrix_id is None:
            raise SaleProductCodeResolveCriticalError("нет текущей матрицы аппарата")
        raise SaleProductCodeResolveCriticalError("матрица не найдена в ответе GetGoodsMatrices")

    if isinstance(matrix, ComboMatrixModel):
        raise SaleProductCodeResolveCriticalError(
            "матрица типа Combo (MatrixType=3): восстановление кода не поддерживается"
        )

    cell = _resolve_matrix_cell(matrix, sale.line)
    if cell is None:
        raise SaleProductCodeResolveCriticalError(
            "ячейка с указанным LineNumber не найдена или тип ячейки не поддерживается"
        )

    if isinstance(matrix, GoodsMatrixModel):
        if isinstance(cell, GoodsCell):
            resolved = cell.product_code
            if resolved is None:
                raise SaleProductCodeResolveCriticalError(
                    "в ячейке матрицы товаров нет кода в GoodsName"
                )
            return resolved
        raise SaleProductCodeResolveCriticalError("ожидалась ячейка товарной матрицы (GoodsCell)")

    if isinstance(matrix, RecipeMatrixModel):
        if not isinstance(cell, RecipeCell):
            raise SaleProductCodeResolveCriticalError(
                "ожидалась ячейка рецептурной матрицы (RecipeCell)"
            )
        recipe = recipes_by_id.get(cell.recipe_id)
        if recipe is None:
            raise SaleProductCodeResolveCriticalError(
                f"рецепт FormulationId={cell.recipe_id} не найден в GetFormulations"
            )
        resolved = recipe.code
        if resolved is None:
            raise SaleProductCodeResolveCriticalError(
                "в названии рецепта нет кода (FormulationName)"
            )
        return resolved

    raise SaleProductCodeResolveCriticalError("неизвестный тип матрицы")


@beartype
def resolve_sales_with_catalog(
    sales: list[SaleModel],
    matrices_by_id: dict[int, MatrixModel],
    recipes_by_id: dict[int, RecipeModel],
    matrix_id_by_vm_id: Mapping[int, int],
    *,
    logger: logging.Logger | None = None,
) -> list[SaleResolvedModel]:
    """Преобразует сырые продажи в разрешённые; ошибки по строкам — log и skip."""
    log = logger if logger is not None else _LOGGER
    result: list[SaleResolvedModel] = []
    for sale in sales:
        try:
            code = resolve_sale_product_code(
                sale,
                matrices_by_id,
                recipes_by_id,
                matrix_id_by_vm_id,
            )
        except SaleProductCodeResolveNonCriticalError as exc:
            log.debug(
                "Пропуск продажи без кода товара (%s): "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                exc,
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
            )
            continue
        except SaleProductCodeResolveCriticalError as exc:
            log.warning(
                "Не удалось определить код товара для продажи (%s): "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                exc,
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
                exc_info=True,
            )
            continue

        vending_machine_code = resolve_sale_vending_machine_code(sale)
        if vending_machine_code is None:
            log.warning(
                "Не удалось определить код аппарата для продажи. "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
            )
            continue

        vending_machine_type = compute_vending_machine_type(vending_machine_code)

        result.append(
            SaleResolvedModel(
                price=sale.price,
                timestamp=sale.timestamp,
                product_code=code,
                vending_machine_code=vending_machine_code,
                vending_machine_type=vending_machine_type,
            )
        )
    return result
