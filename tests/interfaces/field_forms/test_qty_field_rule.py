from __future__ import annotations

from decimal import Decimal

import pytest

from src.interfaces.field_forms.qty_field_rule import (
    make_qty_field_rule,
    parse_qty_against_rule,
)


def test_parse_qty_against_rule_happy_in_range() -> None:
    rule = make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal("99"),
        integer=True,
    )
    assert parse_qty_against_rule("15с", rule, label="Молоко") == Decimal("15")


def test_parse_qty_against_rule_rejects_over_max() -> None:
    rule = make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal("100"),
        integer=False,
    )
    with pytest.raises(ValueError, match="превышать 100 для Сливки"):
        parse_qty_against_rule("101", rule, label="Сливки")


def test_parse_qty_against_rule_rejects_non_integer_when_required() -> None:
    rule = make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal("99"),
        integer=True,
    )
    with pytest.raises(ValueError, match="целым"):
        parse_qty_against_rule("1.5", rule, label="d-1")


def test_qty_field_rule_attrs() -> None:
    rule = make_qty_field_rule(
        min_qty=Decimal("0"),
        max_qty=Decimal("100000"),
        integer=False,
    )
    assert rule.min_attr == "0"
    assert rule.max_attr == "100000"
