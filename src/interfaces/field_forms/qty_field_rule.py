"""Per-line FieldForm text-qty rules shared by POST and HTML projection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.interfaces.google_forms.webhook.inventory_qty_parse import parse_inventory_form_qty


@beartype
@dataclass(frozen=True, slots=True)
class QtyFieldRule:
    """SoT bounds/type for one open qty field (POST + ``data-*`` on GET)."""

    min_qty: Decimal
    max_qty: Decimal
    integer: bool
    required: bool = True

    @property
    def min_attr(self) -> str:
        return _format_bound(self.min_qty)

    @property
    def max_attr(self) -> str:
        return _format_bound(self.max_qty)


@beartype
def make_qty_field_rule(
    *,
    min_qty: Decimal,
    max_qty: Decimal,
    integer: bool,
    required: bool = True,
) -> QtyFieldRule:
    return QtyFieldRule(
        min_qty=min_qty,
        max_qty=max_qty,
        integer=integer,
        required=required,
    )


@beartype
def parse_qty_against_rule(raw: str, rule: QtyFieldRule, *, label: str) -> Decimal:
    """Parse and apply ``rule``; raises ``ValueError`` with RU message + label."""
    stripped = raw.strip()
    if stripped == "":
        raise ValueError(f"Нужен ответ для {label}")
    try:
        qty = parse_inventory_form_qty(stripped)
    except ValueError as error:
        raise ValueError(f"Некорректное количество для {label}") from error
    if qty < 0:
        raise ValueError(f"Количество не может быть отрицательным для {label}")
    if rule.integer and qty != qty.to_integral_value():
        raise ValueError(f"Количество должно быть целым для {label}")
    if qty < rule.min_qty:
        raise ValueError(
            f"Количество не должно быть меньше {rule.min_attr} для {label}",
        )
    if qty > rule.max_qty:
        raise ValueError(
            f"Количество не должно превышать {rule.max_attr} для {label}",
        )
    return qty


@beartype
def _format_bound(value: Decimal) -> str:
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
