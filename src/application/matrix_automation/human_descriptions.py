from __future__ import annotations

from beartype import beartype

from src.application.matrix_automation.deploy_reasons import (
    INVALID_MATRIX_HEADER,
    INVALID_MATRIX_MULTIPLIER,
    PRODUCT_REFERENCE_INVALID,
    UNKNOWN_PRODUCT_NAME,
)

_HEADER_PREFIX = "invalid_matrix_header: "


@beartype
def human_description_for(*, deploy_reason: str, detail: str) -> str:
    if deploy_reason == UNKNOWN_PRODUCT_NAME:
        return "Имя товара не найдено в листе „Товары“"
    if deploy_reason == INVALID_MATRIX_MULTIPLIER:
        if detail.endswith(": missing"):
            return "Множитель матрицы не указан в шапке листа"
        return "Некорректный множитель матрицы в шапке листа"
    if deploy_reason == PRODUCT_REFERENCE_INVALID:
        return "Ошибка в справочнике товаров или множителях"
    if deploy_reason == INVALID_MATRIX_HEADER:
        subcode = detail.removeprefix(_HEADER_PREFIX)
        mapping = {
            "no_machines": "В шапке матрицы не указаны аппараты",
            "duplicate_machine_code": "В шапке матрицы дублируется код аппарата",
            "invalid_matrix_name": "Не удалось определить имя матрицы на листе",
            "invalid_machine_code": "Некорректный код аппарата в шапке матрицы",
            "duplicate_line_number": "В матрице дублируется номер линии",
        }
        for key, text in mapping.items():
            if subcode.startswith(key):
                return text
    return detail
