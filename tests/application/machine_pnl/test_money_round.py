from __future__ import annotations

from decimal import Decimal

from src.application.machine_pnl.money import round_money


def test_money_round_half_up_two_places() -> None:
    assert round_money(Decimal("1.005")) == Decimal("1.01")
    assert round_money(Decimal("1.004")) == Decimal("1.00")
