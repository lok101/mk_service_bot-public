from __future__ import annotations

from decimal import Decimal

import pytest

from src.interfaces.google_forms.webhook.inventory_qty_parse import parse_inventory_form_qty


def test_parse_inventory_form_qty_strips_letters() -> None:
    """happy: letters ignored — ``15с`` → 15."""
    assert parse_inventory_form_qty("15с") == Decimal("15")
    assert parse_inventory_form_qty("15 шт") == Decimal("15")
    assert parse_inventory_form_qty("pcs15") == Decimal("15")


def test_parse_inventory_form_qty_plain_number() -> None:
    assert parse_inventory_form_qty("7") == Decimal("7")
    assert parse_inventory_form_qty(" 3.5 ") == Decimal("3.5")
    assert parse_inventory_form_qty("3,5") == Decimal("3.5")


def test_parse_inventory_form_qty_rejects_empty_after_strip() -> None:
    """error: only letters / empty."""
    with pytest.raises(ValueError):
        parse_inventory_form_qty("шт")
    with pytest.raises(ValueError):
        parse_inventory_form_qty("   ")
