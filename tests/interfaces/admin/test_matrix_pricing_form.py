from __future__ import annotations

from decimal import Decimal

import pytest

from src.interfaces.admin.matrix_pricing_form import (
    base_margin_params_from_form,
    format_rate_percent,
    parse_rate_percent,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("65", Decimal("0.65")),
        ("65%", Decimal("0.65")),
        ("65 %", Decimal("0.65")),
        ("40,5", Decimal("0.405")),
        ("40,5%", Decimal("0.405")),
        ("0.65", Decimal("0.65")),
        ("0,2", Decimal("0.2")),
        ("20", Decimal("0.2")),
        ("200", Decimal("2")),
    ],
)
def test_parse_rate_percent(raw: str, expected: Decimal) -> None:
    assert parse_rate_percent(raw) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("0.65"), "65"),
        (Decimal("0.2"), "20"),
        (Decimal("0.405"), "40,5"),
        (Decimal("2"), "200"),
    ],
)
def test_format_rate_percent(rate: Decimal, expected: str) -> None:
    assert format_rate_percent(rate) == expected


def test_base_margin_params_from_form_accepts_percent_rates() -> None:
    params = base_margin_params_from_form(
        {
            "scale_price_min": "70",
            "scale_price_max": "150",
            "scale_rate_max": "65",
            "scale_rate_min": "40",
            "curvature": "2",
            "margin_floor": "30",
            "rounding_last_digits": "4,9",
        }
    )
    assert params.scale_rate_max == Decimal("0.65")
    assert params.scale_rate_min == Decimal("0.4")


def test_base_margin_params_from_form_accepts_comma_decimal() -> None:
    # happy: scale_price_min=12,5
    fields = {
        "scale_price_min": "12,5",
        "scale_price_max": "100",
        "scale_rate_max": "50",
        "scale_rate_min": "10",
        "curvature": "1",
        "margin_floor": "0",
        "rounding_last_digits": "",
    }
    params = base_margin_params_from_form(fields)
    assert params.scale_price_min == Decimal("12.5")
