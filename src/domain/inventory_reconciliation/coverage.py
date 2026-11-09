from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from beartype import beartype

ReconciliationStatus = Literal["complete", "pending_sales"]


@beartype
def resolve_reconciliation_status(
    *,
    closed_at: datetime,
    machine_last_occurred_at: datetime | None,
    global_cursor: datetime | None,
    tolerance_seconds: int,
    bom_coverage_ok: bool = True,
) -> ReconciliationStatus:
    if not bom_coverage_ok:
        return "pending_sales"
    threshold = closed_at - timedelta(seconds=tolerance_seconds)
    machine_ok = machine_last_occurred_at is not None and machine_last_occurred_at >= threshold
    cursor_ok = global_cursor is not None and global_cursor >= threshold
    if machine_ok or cursor_ok:
        return "complete"
    return "pending_sales"
