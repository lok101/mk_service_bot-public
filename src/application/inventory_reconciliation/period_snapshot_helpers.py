from __future__ import annotations

import logging
from datetime import datetime, timedelta

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.sales_prepare import PreparedCoffeeSales
from src.domain.form_submission import FormSubmissionSnapshot
from src.domain.ids import MachineId
from src.domain.inventory_reconciliation.calculate import calculate_period_reconciliation
from src.domain.inventory_reconciliation.errors import (
    DuplicateProductCodeInStock,
    NaiveDatetimeNotAllowed,
)
from src.domain.inventory_reconciliation.models import (
    PeriodLoadLine,
    PeriodReconciliationResult,
    PeriodRevisionStock,
    ReconciliationLine,
)
from src.domain.inventory_reconciliation.snapshot import FrozenLoadLine
from src.domain.machine_operations.events import LoadingSubmitted
from src.domain.quantities import packages_to_base_quantity

# Preserve the original log channel name from close_period.py so existing
# log filters keep matching after the module was split.
logger = logging.getLogger("src.application.inventory_reconciliation.close_period")

PeriodReconciliationDomainError = DuplicateProductCodeInStock | NaiveDatetimeNotAllowed


@beartype
def _stock_from_submission(snapshot: FormSubmissionSnapshot) -> PeriodRevisionStock:
    return PeriodRevisionStock(
        lines=tuple(
            (line.product_spec.product_code, line.quantity) for line in snapshot.validated_lines
        ),
    )


@beartype
def _loads_in_window(
    loadings: tuple[LoadingSubmitted, ...],
    form_submission_store: FormSubmissionStore,
    *,
    opened_at: datetime,
    closed_at: datetime,
) -> tuple[tuple[PeriodLoadLine, ...], tuple[FrozenLoadLine, ...]]:
    period_loads: list[PeriodLoadLine] = []
    frozen_loads: list[FrozenLoadLine] = []
    for loading in loadings:
        if not opened_at < loading.occurred_at <= closed_at:
            continue
        submission = form_submission_store.get_by_event_id(loading.event_id.value)
        if submission is None:
            raise NonRetryableOutboxError(
                f"Loading form submission was not found for event {loading.event_id.value}",
            )
        for line in submission.validated_lines:
            pack_size = line.product_spec.pack_size
            if pack_size is None or pack_size <= 0:
                raise NonRetryableOutboxError(
                    "Pack size must be configured for loading product "
                    f"{line.product_spec.product_code!r}",
                )
            base_quantity = packages_to_base_quantity(
                packages=line.quantity,
                pack_size=pack_size,
            )
            period_loads.append(
                PeriodLoadLine(
                    product_code=line.product_spec.product_code,
                    occurred_at=loading.occurred_at,
                    input_quantity=line.quantity,
                    input_unit="package",
                    pack_size=pack_size,
                    base_quantity=base_quantity,
                ),
            )
            frozen_loads.append(
                FrozenLoadLine(
                    product_code=line.product_spec.product_code,
                    occurred_at=loading.occurred_at,
                    input_quantity=line.quantity,
                    input_unit="package",
                    pack_size=pack_size,
                    base_quantity=base_quantity,
                    loading_event_id=loading.event_id.value,
                ),
            )
    return tuple(period_loads), tuple(frozen_loads)


@beartype
def _period_loads_from_frozen(
    load_lines: tuple[FrozenLoadLine, ...],
) -> tuple[PeriodLoadLine, ...]:
    return tuple(
        PeriodLoadLine(
            product_code=line.product_code,
            occurred_at=line.occurred_at,
            input_quantity=line.input_quantity,
            input_unit=line.input_unit,
            pack_size=line.pack_size,
            base_quantity=line.base_quantity,
        )
        for line in load_lines
    )


@beartype
def _stock_from_lines(
    lines: tuple[ReconciliationLine, ...],
    *,
    stock_field: str,
) -> PeriodRevisionStock:
    if stock_field == "actual_prev":
        return PeriodRevisionStock(
            lines=tuple((line.product_code, line.actual_prev) for line in lines),
        )
    return PeriodRevisionStock(
        lines=tuple((line.product_code, line.actual) for line in lines),
    )


@beartype
def _log_domain_error(
    *,
    error: PeriodReconciliationDomainError,
    period_id: str,
    machine_id: MachineId,
) -> None:
    logger.warning(
        "period_reconciliation_domain_error",
        extra={
            "error_type": type(error).__name__,
            "period_id": period_id,
            "machine_id": machine_id.value,
        },
    )


@beartype
def _log_pending_reconciliation(
    *,
    period_id: str,
    machine_id: MachineId,
    closed_at: datetime,
    machine_last_occurred_at: datetime | None,
    global_cursor: datetime | None,
    tolerance_seconds: int,
    bom_coverage_ok: bool,
    unresolved_bundle_codes: tuple[str, ...],
) -> None:
    threshold = closed_at - timedelta(seconds=tolerance_seconds)
    machine_ok = machine_last_occurred_at is not None and machine_last_occurred_at >= threshold
    cursor_ok = global_cursor is not None and global_cursor >= threshold
    sales_ok = machine_ok or cursor_ok
    bom_ok = bom_coverage_ok
    if not sales_ok and not bom_ok:
        blocking_reason = "both"
    elif not bom_ok:
        blocking_reason = "bom"
    else:
        blocking_reason = "sales"

    log_fn = logger.info if blocking_reason == "sales" else logger.warning
    log_fn(
        "period_reconciliation_pending_sales",
        extra={
            "blocking_reason": blocking_reason,
            "period_id": period_id,
            "machine_id": machine_id.value,
            "machine_last_occurred_at": (
                None if machine_last_occurred_at is None else machine_last_occurred_at.isoformat()
            ),
            "global_cursor": None if global_cursor is None else global_cursor.isoformat(),
        },
    )
    if not bom_ok:
        logger.warning(
            "bom_recipe_missing",
            extra={
                "bundle_codes": list(unresolved_bundle_codes),
                "period_id": period_id,
            },
        )


@beartype
def _raise_on_domain_error(
    result: PeriodReconciliationResult | PeriodReconciliationDomainError,
    *,
    period_id: str,
    machine_id: MachineId,
) -> PeriodReconciliationResult:
    if isinstance(result, PeriodReconciliationDomainError):
        _log_domain_error(error=result, period_id=period_id, machine_id=machine_id)
        raise NonRetryableOutboxError(type(result).__name__)
    return result


@beartype
def _compute_reconciliation_lines(
    *,
    opening_submission: FormSubmissionSnapshot,
    closing_submission: FormSubmissionSnapshot,
    loads: tuple[PeriodLoadLine, ...],
    prepared: PreparedCoffeeSales,
    opened_at: datetime,
    closed_at: datetime,
    period_id: str,
    machine_id: MachineId,
) -> tuple[ReconciliationLine, ...]:
    result = _raise_on_domain_error(
        calculate_period_reconciliation(
            actual_prev=_stock_from_submission(opening_submission),
            actual=_stock_from_submission(closing_submission),
            loads=loads,
            sales=prepared.period_sales,
            opened_at=opened_at,
            closed_at=closed_at,
        ),
        period_id=period_id,
        machine_id=machine_id,
    )
    return tuple(result.lines_by_product[code] for code in sorted(result.lines_by_product))
