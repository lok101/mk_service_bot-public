from __future__ import annotations

import pytest

from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel


def test_sale_model_validate_json_row() -> None:
    payload = {
        "LineNumber": 1,
        "Sum": 50.0,
        "DateTime": "01.05.2026 12:00:00",
        "GoodsName": "2312 | Капучино",
        "VendingMachine": 99,
        "VendingMachineName": "Кофе [129]",
        "MatrixId": 5,
    }
    sale = SaleModel.model_validate(payload)
    assert sale.product_code == "2312"
    assert sale.vending_machine_code == "129"
    assert sale.timestamp.tzinfo is not None


@pytest.mark.parametrize("matrix_id_raw", ["", 0, None])
def test_sale_model_matrix_id_falsy_becomes_none(matrix_id_raw: object) -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | X",
            "VendingMachine": 1,
            "VendingMachineName": "[129]",
            "MatrixId": matrix_id_raw,
        }
    )
    assert sale.matrix_id is None


def test_sale_model_preserves_line_minus_one() -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": -1,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "Товар 0",
            "VendingMachine": 1,
            "VendingMachineName": "[129]",
            "MatrixId": None,
        }
    )
    assert sale.line == -1


def test_sale_model_parses_company_from_get_sales() -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 50.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | Капучино",
            "VendingMachine": 99,
            "VendingMachineName": "Кофе [129]",
            "MatrixId": 5,
            "Company": 396672,
        }
    )
    assert sale.company_id == 396672


def test_sale_model_parses_company_id_alias_fallback() -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 50.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | Капучино",
            "VendingMachine": 99,
            "VendingMachineName": "Кофе [129]",
            "MatrixId": 5,
            "CompanyId": 42,
        }
    )
    assert sale.company_id == 42


def test_sale_model_missing_company_id_is_none() -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 50.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | Капучино",
            "VendingMachine": 99,
            "VendingMachineName": "Кофе [129]",
            "MatrixId": 5,
        }
    )
    assert sale.company_id is None


@pytest.mark.parametrize("field_name", ["Company", "CompanyId"])
@pytest.mark.parametrize("company_id_raw", ["", None])
def test_sale_model_empty_company_id_is_none(field_name: str, company_id_raw: object) -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 1,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | X",
            "VendingMachine": 1,
            "VendingMachineName": "[129]",
            "MatrixId": None,
            field_name: company_id_raw,
        }
    )
    assert sale.company_id is None
