from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.blocking import build_blocking_empty_line


def test_blocking_empty_line() -> None:
    line = build_blocking_empty_line(line_number=3, blocking_price=Decimal("999"))
    assert line.product_code is None
    assert line.deploy_price == Decimal("999")
    assert line.capacity == 0
    assert line.outcome == "blocked_empty"
