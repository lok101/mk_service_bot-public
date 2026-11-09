from __future__ import annotations

from decimal import Decimal

from src.application.inventory_reconciliation.ms_registrar_ports import StockDocumentLine
from src.infrastructure.integrations.moysklad.quantities import (
    stock_document_lines_to_as_sold_positions,
)


def test_as_sold_positions_pass_through_quantity_and_price() -> None:
    lines = [
        StockDocumentLine(product_code="P1", quantity=Decimal("3"), price_kop=12500),
        StockDocumentLine(product_code="D1", quantity=Decimal("1.5"), price_kop=9900),
    ]
    positions = stock_document_lines_to_as_sold_positions(lines)
    assert positions[0].product_code == "P1"
    assert positions[0].quantity == 3
    assert positions[0].price == 12500
    assert positions[1].product_code == "D1"
    assert positions[1].quantity == 1.5
    assert positions[1].price == 9900


def test_as_sold_positions_ignore_vitrine_factor() -> None:
    """Regression: even if a vitrine factor would be 0.001, as-sold keeps sales qty."""
    lines = [StockDocumentLine(product_code="G1", quantity=Decimal("1000"), price_kop=100)]
    positions = stock_document_lines_to_as_sold_positions(lines)
    assert positions[0].quantity == 1000  # not 1.0
