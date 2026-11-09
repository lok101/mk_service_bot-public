from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import EventId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested
from src.domain.machine_sales_classify import is_snack_machine_code

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class MachinePnlEventPublisher(Protocol):
    """Narrow publish port; satisfied by OutboxDomainEventPublisher."""

    @beartype
    def publish(self, event: DomainEvent) -> None: ...


@beartype
def _months_overlapping(opened_at: datetime, closed_at: datetime) -> tuple[date, ...]:
    start = opened_at.astimezone(UTC).date().replace(day=1)
    end = closed_at.astimezone(UTC).date().replace(day=1)
    months: list[date] = []
    current = start
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return tuple(months)


@beartype
def enqueue_machine_period_pnl_jobs(
    *,
    period_ids: tuple[str, ...] | list[str],
    snapshots_by_id: Mapping[str, ResponsibilityPeriodReconciliation],
    source_session_id: str,
    publisher: MachinePnlEventPublisher,
    occurred_at: datetime | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else datetime.now(tz=UTC)
    for period_id in period_ids:
        snapshot = snapshots_by_id.get(period_id)
        if snapshot is None:
            _LOGGER.warning(
                "machine_pnl enqueue skip missing_snapshot period_id=%s",
                period_id,
            )
            continue
        if is_snack_machine_code(snapshot.machine_id.value):
            _LOGGER.info(
                "machine_pnl enqueue skip snack period_id=%s machine_id=%s",
                period_id,
                snapshot.machine_id.value,
            )
            continue
        if snapshot.status != "complete":
            _LOGGER.info(
                "machine_pnl enqueue skip incomplete period_id=%s status=%s",
                period_id,
                snapshot.status,
            )
            continue
        if not snapshot.reconciled:
            _LOGGER.info(
                "machine_pnl enqueue skip not_reconciled period_id=%s",
                period_id,
            )
            continue
        publisher.publish(
            MachinePeriodPnlRequested(
                event_id=EventId(f"machine_pnl:{period_id}"),
                period_id=period_id,
                source_session_id=source_session_id,
                occurred_at=now,
            )
        )
        publisher.publish(
            MachineMonthPnlRequested(
                event_id=EventId(f"machine_pnl_month:{period_id}"),
                machine_id=snapshot.machine_id.value,
                period_start_dates=_months_overlapping(snapshot.opened_at, snapshot.closed_at),
                source_period_id=period_id,
                occurred_at=now,
            )
        )
