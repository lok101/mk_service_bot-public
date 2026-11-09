from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from random import Random

from hypothesis import example, given, settings
from hypothesis import strategies as st

from src.domain.inventory_reconciliation.calculate import calculate_period_reconciliation
from src.domain.inventory_reconciliation.errors import (
    DuplicateProductCodeInStock,
    NaiveDatetimeNotAllowed,
)
from src.domain.inventory_reconciliation.models import (
    PeriodLoadLine,
    PeriodReconciliationResult,
    PeriodRevisionStock,
    PeriodSaleLine,
)

from .strategies import NON_NEGATIVE_SKU_MAPS, SKU_MAPS

_OPENED_AT = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED_AT = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_INSIDE_WINDOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

_EMPTY_OPENING: dict[str, Decimal] = {}
_EMPTY_CLOSING: dict[str, Decimal] = {}
_EMPTY_LOADS: dict[str, Decimal] = {}
_EMPTY_SALES: dict[str, Decimal] = {}
_MIXED_OPENING = {"coffee": Decimal("-5.500")}
_MIXED_CLOSING = {"coffee": Decimal("3.250")}
_MIXED_LOADS = {"coffee": Decimal("1.000")}
_MIXED_SALES = {"coffee": Decimal("0.250")}
_SCALE_OPENING = {"coffee": Decimal("1.125")}
_SCALE_CLOSING = {"coffee": Decimal("0.250")}
_SCALE_LOADS = {"coffee": Decimal("0.250")}
_SCALE_SALES = {"coffee": Decimal("1.125")}

PeriodReconciliationOutcome = (
    PeriodReconciliationResult | DuplicateProductCodeInStock | NaiveDatetimeNotAllowed
)


def _oracle_delta(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: dict[str, Decimal],
    sales: dict[str, Decimal],
    sku: str,
) -> Decimal:
    return (
        closing.get(sku, Decimal("0"))
        - opening.get(sku, Decimal("0"))
        - loads.get(sku, Decimal("0"))
        + sales.get(sku, Decimal("0"))
    )


def _stock(mapping: dict[str, Decimal]) -> PeriodRevisionStock:
    return PeriodRevisionStock(lines=tuple(mapping.items()))


def _load_lines(mapping: dict[str, Decimal]) -> tuple[PeriodLoadLine, ...]:
    return tuple(
        PeriodLoadLine(
            product_code=sku,
            occurred_at=_INSIDE_WINDOW,
            input_quantity=qty,
            input_unit="package",
            pack_size=Decimal("1"),
            base_quantity=qty,
        )
        for sku, qty in mapping.items()
    )


def _sale_lines(mapping: dict[str, Decimal]) -> tuple[PeriodSaleLine, ...]:
    return tuple(
        PeriodSaleLine(product_code=sku, quantity=qty, occurred_at=_INSIDE_WINDOW)
        for sku, qty in mapping.items()
    )


def _adapt_and_calculate_from_lines(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: tuple[PeriodLoadLine, ...],
    sales: tuple[PeriodSaleLine, ...],
    *,
    opened_at: datetime = _OPENED_AT,
    closed_at: datetime = _CLOSED_AT,
) -> PeriodReconciliationOutcome:
    return calculate_period_reconciliation(
        actual_prev=_stock(opening),
        actual=_stock(closing),
        loads=loads,
        sales=sales,
        opened_at=opened_at,
        closed_at=closed_at,
    )


def _adapt_and_calculate(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: dict[str, Decimal],
    sales: dict[str, Decimal],
    *,
    opened_at: datetime = _OPENED_AT,
    closed_at: datetime = _CLOSED_AT,
) -> PeriodReconciliationOutcome:
    return _adapt_and_calculate_from_lines(
        opening,
        closing,
        _load_lines(loads),
        _sale_lines(sales),
        opened_at=opened_at,
        closed_at=closed_at,
    )


@given(opening=SKU_MAPS, closing=SKU_MAPS, loads=NON_NEGATIVE_SKU_MAPS, sales=NON_NEGATIVE_SKU_MAPS)
@example(opening=_EMPTY_OPENING, closing=_EMPTY_CLOSING, loads=_EMPTY_LOADS, sales=_EMPTY_SALES)
@example(opening=_MIXED_OPENING, closing=_MIXED_CLOSING, loads=_MIXED_LOADS, sales=_MIXED_SALES)
@example(opening=_SCALE_OPENING, closing=_SCALE_CLOSING, loads=_SCALE_LOADS, sales=_SCALE_SALES)
@settings(max_examples=200)
def test_reconciliation_conservation_for_generated_sku_maps(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: dict[str, Decimal],
    sales: dict[str, Decimal],
) -> None:
    """INV-REC-001: closing = opening + loads - sales + delta for each SKU."""
    result = _adapt_and_calculate(opening, closing, loads, sales)
    assert isinstance(result, PeriodReconciliationResult)
    for sku in set(opening) | set(closing) | set(loads) | set(sales):
        line = result.lines_by_product[sku]
        assert line.actual == closing.get(sku, Decimal("0"))
        assert line.actual_prev == opening.get(sku, Decimal("0"))
        assert line.loads_total == loads.get(sku, Decimal("0"))
        assert line.sales_total == sales.get(sku, Decimal("0"))
        assert line.delta == _oracle_delta(opening, closing, loads, sales, sku)
        assert line.actual == line.actual_prev + line.loads_total - line.sales_total + line.delta


@given(
    opening=SKU_MAPS,
    closing=SKU_MAPS,
    loads=NON_NEGATIVE_SKU_MAPS,
    sales=NON_NEGATIVE_SKU_MAPS,
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
@example(
    opening=_EMPTY_OPENING,
    closing=_EMPTY_CLOSING,
    loads=_EMPTY_LOADS,
    sales=_EMPTY_SALES,
    seed=0,
)
@example(
    opening=_MIXED_OPENING,
    closing=_MIXED_CLOSING,
    loads=_MIXED_LOADS,
    sales=_MIXED_SALES,
    seed=1,
)
@settings(max_examples=200)
def test_reconciliation_is_permutation_invariant(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: dict[str, Decimal],
    sales: dict[str, Decimal],
    seed: int,
) -> None:
    """INV-REC-002: independent SKU/line order does not change reconciliation."""
    result = _adapt_and_calculate(opening, closing, loads, sales)
    assert isinstance(result, PeriodReconciliationResult)
    rng = Random(seed)
    load_lines = list(_load_lines(loads))
    sale_lines = list(_sale_lines(sales))
    rng.shuffle(load_lines)
    rng.shuffle(sale_lines)
    permuted = _adapt_and_calculate_from_lines(
        opening,
        closing,
        tuple(load_lines),
        tuple(sale_lines),
    )
    assert isinstance(permuted, PeriodReconciliationResult)
    assert permuted.lines_by_product == result.lines_by_product


@given(opening=SKU_MAPS, closing=SKU_MAPS, loads=NON_NEGATIVE_SKU_MAPS, sales=NON_NEGATIVE_SKU_MAPS)
@settings(max_examples=200)
def test_zero_line_does_not_change_nonzero_reconciliation(
    opening: dict[str, Decimal],
    closing: dict[str, Decimal],
    loads: dict[str, Decimal],
    sales: dict[str, Decimal],
) -> None:
    extra_sku = "zero-extra"
    assert extra_sku not in set(opening) | set(closing) | set(loads) | set(sales)
    baseline = _adapt_and_calculate(opening, closing, loads, sales)
    assert isinstance(baseline, PeriodReconciliationResult)
    with_zero = _adapt_and_calculate(
        {**opening, extra_sku: Decimal("0")},
        {**closing, extra_sku: Decimal("0")},
        {**loads, extra_sku: Decimal("0")},
        {**sales, extra_sku: Decimal("0")},
    )
    assert isinstance(with_zero, PeriodReconciliationResult)
    for sku, line in baseline.lines_by_product.items():
        assert with_zero.lines_by_product[sku] == line


def test_empty_reconciliation_returns_empty_result() -> None:
    result = _adapt_and_calculate({}, {}, {}, {})
    assert isinstance(result, PeriodReconciliationResult)
    assert result.lines_by_product == {}


def test_reconciliation_conservation_for_three_decimal_place_values() -> None:
    result = _adapt_and_calculate(_SCALE_OPENING, _SCALE_CLOSING, _SCALE_LOADS, _SCALE_SALES)
    assert isinstance(result, PeriodReconciliationResult)
    line = result.lines_by_product["coffee"]
    assert line.delta == _oracle_delta(
        _SCALE_OPENING,
        _SCALE_CLOSING,
        _SCALE_LOADS,
        _SCALE_SALES,
        "coffee",
    )
    assert line.delta == Decimal("0.000")


@given(naive=st.datetimes().map(lambda value: value.replace(tzinfo=None)))
@settings(max_examples=50)
def test_reconciliation_rejects_generated_naive_datetime(naive: datetime) -> None:
    result = _adapt_and_calculate(
        {"coffee": Decimal("1")},
        {"coffee": Decimal("1")},
        {},
        {},
        opened_at=naive,
    )
    assert isinstance(result, NaiveDatetimeNotAllowed)


def test_reconciliation_rejects_duplicate_product_code_in_stock() -> None:
    result = calculate_period_reconciliation(
        actual_prev=PeriodRevisionStock(
            lines=(("coffee", Decimal("1")), ("coffee", Decimal("2"))),
        ),
        actual=PeriodRevisionStock(lines=()),
        loads=(),
        sales=(),
        opened_at=_OPENED_AT,
        closed_at=_CLOSED_AT,
    )
    assert isinstance(result, DuplicateProductCodeInStock)
    assert result.product_code == "coffee"
    assert result.source == "actual_prev"
