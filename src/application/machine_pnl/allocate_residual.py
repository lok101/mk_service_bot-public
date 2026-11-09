from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.errors import (
    IncompleteSnapshotError,
    MissingUnitCostError,
    SnapshotNotFoundError,
)
from src.application.machine_pnl.models import PnlWarning
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.ports import PeriodSnapshotReader, UnitCostCatalog
from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales_classify import is_snack_machine_code

_ZERO = Decimal("0")


@beartype
@dataclass(frozen=True, slots=True)
class ResidualAllocation:
    allocated_shortage: Decimal
    allocated_surplus: Decimal
    warnings: tuple[PnlWarning, ...]


def _sales_total_for_sku(
    snapshot: ResponsibilityPeriodReconciliation,
    sku: str,
) -> Decimal:
    for line in snapshot.lines:
        if line.product_code == sku:
            return line.sales_total
    return _ZERO


def _weight_for_period(snapshot: ResponsibilityPeriodReconciliation, sku: str) -> Decimal:
    if is_snack_machine_code(snapshot.machine_id.value):
        return _ZERO
    sales_total = _sales_total_for_sku(snapshot, sku)
    if sales_total < _ZERO:
        return _ZERO
    return sales_total


def _load_siblings(
    session: ResidualSessionView,
    snapshots: PeriodSnapshotReader,
) -> dict[str, ResponsibilityPeriodReconciliation]:
    loaded: dict[str, ResponsibilityPeriodReconciliation] = {}
    for sibling_id in session.period_ids:
        sibling = snapshots.get_by_period_id(sibling_id)
        if sibling is None:
            raise SnapshotNotFoundError(sibling_id)
        if sibling.status != "complete":
            raise IncompleteSnapshotError(sibling_id, status=sibling.status)
        if not sibling.reconciled:
            raise IncompleteSnapshotError(sibling_id, status="unreconciled")
        loaded[sibling_id] = sibling
    return loaded


@beartype
def allocate_residual_for_period(
    *,
    period_id: str,
    session: ResidualSessionView,
    snapshots: PeriodSnapshotReader,
    unit_cost_catalog: UnitCostCatalog,
) -> ResidualAllocation:
    as_of = session.anchor_at.date()
    shortage_sum = _ZERO
    surplus_sum = _ZERO
    warnings: list[PnlWarning] = []
    siblings: dict[str, ResponsibilityPeriodReconciliation] | None = None

    for sku in sorted(session.residual_by_sku.keys()):
        residual_qty = session.residual_by_sku[sku]
        if residual_qty == _ZERO:
            continue
        if siblings is None:
            siblings = _load_siblings(session, snapshots)

        weights: dict[str, Decimal] = {
            pid: _weight_for_period(snap, sku) for pid, snap in siblings.items()
        }
        total_weight = sum(weights.values(), start=_ZERO)
        if total_weight == _ZERO:
            warnings.append(
                PnlWarning(
                    code="unallocatable_residual",
                    message=f"unallocatable residual for {sku} residual={residual_qty}",
                    sku=sku,
                )
            )
            continue

        unit_cost = unit_cost_catalog.get(sku, as_of=as_of)
        if unit_cost is None:
            raise MissingUnitCostError(
                product_code=sku,
                as_of=as_of.isoformat(),
                period_id=period_id,
            )

        money_total = abs(residual_qty) * unit_cost
        w_current = weights.get(period_id, _ZERO)
        share = money_total * (w_current / total_weight)
        if residual_qty < _ZERO:
            shortage_sum += share
        else:
            surplus_sum += share

    allocated_shortage = round_money(shortage_sum)
    allocated_surplus = round_money(surplus_sum)
    if allocated_surplus != _ZERO:
        warnings.append(
            PnlWarning(
                code="allocated_surplus_nonzero",
                message=f"allocated_surplus={allocated_surplus}",
                sku=None,
            )
        )

    return ResidualAllocation(
        allocated_shortage=allocated_shortage,
        allocated_surplus=allocated_surplus,
        warnings=tuple(warnings),
    )
