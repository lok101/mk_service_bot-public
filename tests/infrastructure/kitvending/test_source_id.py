from __future__ import annotations

from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel
from src.infrastructure.integrations.kitvending.source_id import build_sale_source_id


def test_build_sale_source_id_format() -> None:
    sale = SaleModel.model_validate(
        {
            "LineNumber": 2,
            "Sum": 1.0,
            "DateTime": "01.05.2026 12:00:00",
            "GoodsName": "2312 | X",
            "VendingMachine": 99,
            "VendingMachineName": "[129]",
            "MatrixId": 5,
        }
    )
    assert build_sale_source_id(sale) == "kit:99:01.05.2026 12:00:00:2:5"
