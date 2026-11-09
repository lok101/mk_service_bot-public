from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationScope:
    scope: tuple[ResponsibilityPeriodReconciliation, ...]
    deferred: tuple[ResponsibilityPeriodReconciliation, ...]
    blockers: tuple[ResponsibilityPeriodReconciliation, ...]
    ledger_balance_session: dict[str, Decimal]


@beartype
def ledger_balance_for(
    periods: tuple[ResponsibilityPeriodReconciliation, ...],
) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for snapshot in periods:
        for line in snapshot.lines:
            if line.delta == Decimal("0"):
                continue
            totals[line.product_code] = totals.get(line.product_code, Decimal("0")) + line.delta
    return {sku: value for sku, value in totals.items() if value != Decimal("0")}


@beartype
def compute_scope(
    *,
    posted_unreconciled: list[ResponsibilityPeriodReconciliation],
    pending_in_window: list[ResponsibilityPeriodReconciliation],
    anchor_at: datetime,
) -> ReconciliationScope:
    scope = tuple(
        sorted(
            (s for s in posted_unreconciled if s.closed_at <= anchor_at),
            key=lambda s: s.period_id,
        ),
    )
    deferred = tuple(
        sorted(
            (s for s in posted_unreconciled if s.closed_at > anchor_at),
            key=lambda s: s.period_id,
        ),
    )
    blockers = tuple(
        sorted(
            (s for s in pending_in_window if s.closed_at <= anchor_at),
            key=lambda s: s.period_id,
        ),
    )
    return ReconciliationScope(
        scope=scope,
        deferred=deferred,
        blockers=blockers,
        ledger_balance_session=ledger_balance_for(scope),
    )
