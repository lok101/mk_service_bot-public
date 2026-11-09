from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _sale(**overrides: object) -> MachineSale:
    base: dict[str, object] = {
        "source_id": "s-1",
        "machine_id": MachineId("m-1"),
        "product_code": "P1",
        "quantity": Decimal("1"),
        "occurred_at": _NOW,
        "ingested_at": _NOW,
    }
    base.update(overrides)
    return MachineSale(**base)  # type: ignore[arg-type]


def test_machine_sale_price_defaults_to_none() -> None:
    assert _sale().price is None


def test_machine_sale_accepts_decimal_price() -> None:
    sale = _sale(price=Decimal("150.50"))
    assert sale.price == Decimal("150.50")
