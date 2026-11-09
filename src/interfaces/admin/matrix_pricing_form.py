from __future__ import annotations

from decimal import Decimal

from beartype import beartype

from src.application.shared import parse_sheet_decimal
from src.domain.matrix_pricing.formula import BaseMarginParams

_MARGIN_REJECTION_MESSAGES: dict[str, str] = {
    "scale_price_out_of_bounds": (
        "Себестоимость вне допустимого диапазона или минимум шкалы не меньше максимума"
    ),
    "scale_rate_out_of_bounds": (
        "Наценка вне допустимого диапазона (10–200%) или минимум больше максимума"
    ),
    "curvature_out_of_bounds": "Изгиб шкалы вне допустимого диапазона",
    "margin_floor_out_of_bounds": "Минимальная наценка вне допустимого диапазона",
}


@beartype
def matrix_pricing_rejection_message(*, code: str, fallback: str) -> str:
    return _MARGIN_REJECTION_MESSAGES.get(code, fallback)


@beartype
def format_rate_percent(rate: Decimal) -> str:
    percent = (rate * Decimal("100")).normalize()
    text = format(percent, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


@beartype
def parse_rate_percent(raw: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise ValueError("missing field: scale_rate")
    is_percent_points = text.endswith("%")
    if is_percent_points:
        text = text[:-1].strip()
    try:
        value = parse_sheet_decimal(text)
    except ValueError as exc:
        raise ValueError("invalid rate percent") from exc
    if is_percent_points or value >= Decimal("1"):
        value /= Decimal("100")
    return value


@beartype
def form_values_from_base_margin(params: BaseMarginParams) -> dict[str, str]:
    rounding = params.rounding_last_digits
    rounding_text = "" if rounding is None else ",".join(str(digit) for digit in sorted(rounding))
    return {
        "scale_price_min": str(params.scale_price_min),
        "scale_price_max": str(params.scale_price_max),
        "scale_rate_max": format_rate_percent(params.scale_rate_max),
        "scale_rate_min": format_rate_percent(params.scale_rate_min),
        "curvature": str(params.curvature),
        "margin_floor": str(params.margin_floor),
        "rounding_last_digits": rounding_text,
    }


@beartype
def base_margin_params_from_form(fields: dict[str, str]) -> BaseMarginParams:
    decimal_fields = (
        "scale_price_min",
        "scale_price_max",
        "curvature",
        "margin_floor",
    )
    values: dict[str, Decimal] = {}
    for key in decimal_fields:
        raw = fields.get(key, "").strip()
        if not raw:
            raise ValueError(f"missing field: {key}")
        try:
            values[key] = parse_sheet_decimal(raw)
        except ValueError as exc:
            raise ValueError(f"invalid decimal: {key}") from exc

    for key in ("scale_rate_max", "scale_rate_min"):
        raw = fields.get(key, "").strip()
        if not raw:
            raise ValueError(f"missing field: {key}")
        try:
            values[key] = parse_rate_percent(raw)
        except ValueError as exc:
            raise ValueError(f"invalid rate: {key}") from exc

    return BaseMarginParams(
        scale_price_min=values["scale_price_min"],
        scale_price_max=values["scale_price_max"],
        scale_rate_max=values["scale_rate_max"],
        scale_rate_min=values["scale_rate_min"],
        curvature=values["curvature"],
        margin_floor=values["margin_floor"],
        rounding_last_digits=_rounding_digits_from_form(fields.get("rounding_last_digits", "")),
    )


@beartype
def _rounding_digits_from_form(raw: str) -> frozenset[int] | None:
    text = raw.strip()
    if not text:
        return None
    digits: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        try:
            digit = int(part)
        except ValueError as exc:
            raise ValueError(f"invalid rounding digit: {part!r}") from exc
        if digit < 0 or digit > 9:
            raise ValueError(f"rounding digit out of range: {digit}")
        digits.add(digit)
    return frozenset(digits) if digits else None
