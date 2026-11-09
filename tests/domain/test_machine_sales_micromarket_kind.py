from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale, SaleKind


def test_sale_kind_micromarket_literal() -> None:
    assert "micromarket" in SaleKind.__args__  # type: ignore[attr-defined]
    kind: SaleKind = "micromarket"
    sale = MachineSale(
        source_id="kitshop:100:1",
        machine_id=MachineId("701"),
        product_code="2311",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 4, tzinfo=UTC),
        sale_kind=kind,
        kit_matrix_id=None,
        kit_vending_machine_id=None,
        kit_line_number=None,
    )
    assert sale.sale_kind == "micromarket"
    assert sale.kit_vending_machine_id is None
