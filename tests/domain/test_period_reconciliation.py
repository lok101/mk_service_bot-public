from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.calculate import calculate_period_reconciliation
from src.domain.inventory_reconciliation.coverage import resolve_reconciliation_status
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
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation

_OPENED = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_ON_OPEN = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_BEFORE = datetime(2026, 6, 1, 9, 59, tzinfo=UTC)
_AFTER = datetime(2026, 6, 8, 10, 0, 1, tzinfo=UTC)
_NAIVE = datetime(2026, 6, 5, 12, 0)


def _load_line(
    product_code: str,
    *,
    base_quantity: Decimal,
    occurred_at: datetime = _INSIDE,
    input_quantity: Decimal | None = None,
    pack_size: Decimal = Decimal("1"),
) -> PeriodLoadLine:
    qty = input_quantity if input_quantity is not None else base_quantity
    return PeriodLoadLine(
        product_code=product_code,
        occurred_at=occurred_at,
        input_quantity=qty,
        input_unit="package",
        pack_size=pack_size,
        base_quantity=base_quantity,
    )


def _require_result(
    result: PeriodReconciliationResult | DuplicateProductCodeInStock | NaiveDatetimeNotAllowed,
) -> PeriodReconciliationResult:
    assert isinstance(result, PeriodReconciliationResult)
    return result


def test_loads_total_uses_base_quantity_not_packages() -> None:
    """2 упак. × 1000 гр → loads_total=2000 в формуле."""
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("1000")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("3000")),)),
            loads=(
                PeriodLoadLine(
                    product_code="coffee-1",
                    occurred_at=_INSIDE,
                    input_quantity=Decimal("2"),
                    input_unit="package",
                    pack_size=Decimal("1000"),
                    base_quantity=Decimal("2000"),
                ),
            ),
            sales=(),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["coffee-1"]
    assert line.loads_total == Decimal("2000")
    assert line.calculated == Decimal("3000")
    assert line.delta == Decimal("0")


def test_calculated_equals_actual_prev_plus_loads_minus_sales() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("100")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("90")),)),
            loads=(_load_line("coffee-1", base_quantity=Decimal("20")),),
            sales=(
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("30"),
                    occurred_at=_INSIDE,
                ),
            ),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["coffee-1"]
    assert line.actual_prev == Decimal("100")
    assert line.actual == Decimal("90")
    assert line.calculated == Decimal("90")  # 100 + 20 - 30
    assert line.delta == Decimal("0")


def test_calculate_includes_loads_and_sales_totals() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("SKU1", Decimal("10")),)),
            actual=PeriodRevisionStock(lines=(("SKU1", Decimal("9")),)),
            loads=(_load_line("SKU1", base_quantity=Decimal("2")),),
            sales=(
                PeriodSaleLine(
                    product_code="SKU1",
                    quantity=Decimal("3"),
                    occurred_at=_INSIDE,
                ),
            ),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["SKU1"]
    assert line.loads_total == Decimal("2")
    assert line.sales_total == Decimal("3")
    assert line.calculated == line.actual_prev + line.loads_total - line.sales_total


def test_window_excludes_sales_on_open_boundary_and_before() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("10")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("10")),)),
            loads=(),
            sales=(
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("5"),
                    occurred_at=_ON_OPEN,
                ),
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("5"),
                    occurred_at=_BEFORE,
                ),
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("3"),
                    occurred_at=_CLOSED,
                ),
            ),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["coffee-1"]
    assert line.calculated == Decimal("7")  # 10 - 3 (only closed_at inclusive)


def test_union_of_skus_from_all_sources() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=()),
            actual=PeriodRevisionStock(lines=(("water-1", Decimal("5")),)),
            loads=(_load_line("coffee-1", base_quantity=Decimal("1")),),
            sales=(),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    assert set(result.lines_by_product) == {"coffee-1", "water-1"}
    assert result.lines_by_product["coffee-1"].actual == Decimal("0")
    assert result.lines_by_product["water-1"].actual == Decimal("5")


def test_rejects_duplicate_product_code_in_actual_prev() -> None:
    result = calculate_period_reconciliation(
        actual_prev=PeriodRevisionStock(
            lines=(("coffee-1", Decimal("1")), ("coffee-1", Decimal("2"))),
        ),
        actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("1")),)),
        loads=(),
        sales=(),
        opened_at=_OPENED,
        closed_at=_CLOSED,
    )
    assert isinstance(result, DuplicateProductCodeInStock)
    assert result.product_code == "coffee-1"
    assert result.source == "actual_prev"


def test_rejects_duplicate_product_code_in_actual() -> None:
    result = calculate_period_reconciliation(
        actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("1")),)),
        actual=PeriodRevisionStock(
            lines=(("coffee-1", Decimal("1")), ("coffee-1", Decimal("2"))),
        ),
        loads=(),
        sales=(),
        opened_at=_OPENED,
        closed_at=_CLOSED,
    )
    assert isinstance(result, DuplicateProductCodeInStock)
    assert result.product_code == "coffee-1"
    assert result.source == "actual"


def test_rejects_naive_opened_at() -> None:
    result = calculate_period_reconciliation(
        actual_prev=PeriodRevisionStock(lines=()),
        actual=PeriodRevisionStock(lines=()),
        loads=(),
        sales=(),
        opened_at=_NAIVE,
        closed_at=_CLOSED,
    )
    assert isinstance(result, NaiveDatetimeNotAllowed)
    assert result.field == "opened_at"


def test_rejects_naive_occurred_at_in_load() -> None:
    result = calculate_period_reconciliation(
        actual_prev=PeriodRevisionStock(lines=()),
        actual=PeriodRevisionStock(lines=()),
        loads=(_load_line("coffee-1", base_quantity=Decimal("1"), occurred_at=_NAIVE),),
        sales=(),
        opened_at=_OPENED,
        closed_at=_CLOSED,
    )
    assert isinstance(result, NaiveDatetimeNotAllowed)
    assert result.field == "loads[0].occurred_at"


def test_window_excludes_sales_after_closed_at() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("10")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("10")),)),
            loads=(),
            sales=(
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("99"),
                    occurred_at=_AFTER,
                ),
            ),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    assert result.lines_by_product["coffee-1"].calculated == Decimal("10")


def test_window_load_on_closed_at_included() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("5")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("8")),)),
            loads=(_load_line("coffee-1", base_quantity=Decimal("3"), occurred_at=_CLOSED),),
            sales=(),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    assert result.lines_by_product["coffee-1"].calculated == Decimal("8")


def test_window_load_on_opened_at_excluded() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("5")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("5")),)),
            loads=(_load_line("coffee-1", base_quantity=Decimal("3"), occurred_at=_ON_OPEN),),
            sales=(),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    assert result.lines_by_product["coffee-1"].calculated == Decimal("5")


def test_aggregates_multiple_sales_same_sku() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("20")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("15")),)),
            loads=(),
            sales=(
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("2"),
                    occurred_at=_INSIDE,
                ),
                PeriodSaleLine(
                    product_code="coffee-1",
                    quantity=Decimal("3"),
                    occurred_at=_INSIDE,
                ),
            ),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["coffee-1"]
    assert line.calculated == Decimal("15")  # 20 - 2 - 3
    assert line.delta == Decimal("0")


def test_non_zero_delta_when_actual_differs_from_calculated() -> None:
    result = _require_result(
        calculate_period_reconciliation(
            actual_prev=PeriodRevisionStock(lines=(("coffee-1", Decimal("10")),)),
            actual=PeriodRevisionStock(lines=(("coffee-1", Decimal("7")),)),
            loads=(),
            sales=(),
            opened_at=_OPENED,
            closed_at=_CLOSED,
        ),
    )
    line = result.lines_by_product["coffee-1"]
    assert line.calculated == Decimal("10")
    assert line.delta == Decimal("-3")


def test_complete_when_last_sale_covers_closed_at() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=datetime(2026, 6, 8, 10, 5, tzinfo=UTC),
        global_cursor=None,
        tolerance_seconds=0,
    )
    assert status == "complete"


def test_complete_when_global_cursor_covers_without_machine_sales() -> None:
    # happy: cursor-only
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=None,
        global_cursor=_CLOSED,
        tolerance_seconds=0,
    )
    assert status == "complete"


def test_pending_sales_when_cursor_behind_closed_at() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        global_cursor=None,
        tolerance_seconds=0,
    )
    assert status == "pending_sales"


def test_pending_sales_when_cursor_and_machine_behind() -> None:
    # edge: neither covers
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        global_cursor=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        tolerance_seconds=0,
    )
    assert status == "pending_sales"


def test_pending_sales_when_no_sales_ingested_yet() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=None,
        global_cursor=None,
        tolerance_seconds=0,
    )
    assert status == "pending_sales"


def test_complete_when_last_sale_exactly_at_closed_at() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=_CLOSED,
        global_cursor=None,
        tolerance_seconds=0,
    )
    assert status == "complete"


def test_pending_sales_when_last_sale_one_second_before_closed_at() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=datetime(2026, 6, 8, 9, 59, 59, tzinfo=UTC),
        global_cursor=None,
        tolerance_seconds=0,
    )
    assert status == "pending_sales"


def test_complete_when_last_sale_within_tolerance() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=datetime(2026, 6, 8, 9, 58, tzinfo=UTC),
        global_cursor=None,
        tolerance_seconds=120,
    )
    assert status == "complete"


def test_complete_when_global_cursor_within_tolerance() -> None:
    # edge: cursor vs tolerance
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=None,
        global_cursor=datetime(2026, 6, 8, 9, 58, tzinfo=UTC),
        tolerance_seconds=120,
    )
    assert status == "complete"


def test_pending_sales_when_bom_not_covered_even_if_ingest_ok() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=_CLOSED,
        global_cursor=_CLOSED,
        tolerance_seconds=0,
        bom_coverage_ok=False,
    )
    assert status == "pending_sales"


def test_complete_when_ingest_and_bom_ok() -> None:
    status = resolve_reconciliation_status(
        closed_at=_CLOSED,
        machine_last_occurred_at=_CLOSED,
        global_cursor=None,
        tolerance_seconds=0,
        bom_coverage_ok=True,
    )
    assert status == "complete"


def test_responsibility_period_reconciliation_defaults() -> None:
    snapshot = ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=False,
        reconciled=False,
    )
    assert snapshot.calculated_source == "domain"
    assert snapshot.ledger_posted is False
    assert snapshot.reconciled is False
