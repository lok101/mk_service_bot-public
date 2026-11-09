from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.micromarket_loading.order import MicromarketLoadingCycle, OrderStatus

_STATUS_LABEL_RU: dict[OrderStatus, str] = {
    OrderStatus.OPEN: "открыта",
    OrderStatus.RECOUNTED: "пересчитана",
    OrderStatus.CLOSED: "закрыта",
    OrderStatus.ROLLED_BACK: "откат",
}


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingTaskRow:
    """Projection of a loading cycle for admin Tasks tabs (not ShopListPublishJournal)."""

    machine_code: str
    order_id: str | None
    status: OrderStatus
    visit_id: str | None
    opened_operational_day: date | None
    sort_at: datetime
    status_label: str
    trigger_label: str
    effects_summary: str
    effects_detail_lines: tuple[str, ...]


@beartype
def project_loading_task_rows(
    cycles: Sequence[MicromarketLoadingCycle],
    *,
    machine_code: str | None = None,
    timezone: ZoneInfo | None = None,
) -> tuple[MicromarketLoadingTaskRow, ...]:
    """Build loading rows for park or single-machine Tasks feed.

    Only cycles with a concrete order status are included (draft-only omitted).
    """
    tz = timezone if timezone is not None else ZoneInfo("UTC")
    rows: list[MicromarketLoadingTaskRow] = []
    for cycle in cycles:
        if cycle.status is None:
            continue
        if machine_code is not None and cycle.machine_code != machine_code:
            continue
        sort_at = _sort_at_for_cycle(cycle, tz=tz)
        visit_line = f"VisitTask {cycle.visit_id}" if cycle.visit_id else "VisitTask не связан"
        order_line = f"Ордер {cycle.order_id}" if cycle.order_id else "Ордер без id"
        rows.append(
            MicromarketLoadingTaskRow(
                machine_code=cycle.machine_code,
                order_id=cycle.order_id,
                status=cycle.status,
                visit_id=cycle.visit_id,
                opened_operational_day=cycle.opened_operational_day,
                sort_at=sort_at,
                status_label=_STATUS_LABEL_RU[cycle.status],
                trigger_label="Загрузка",
                effects_summary=order_line,
                effects_detail_lines=(order_line, visit_line),
            )
        )
    rows.sort(key=lambda row: (row.sort_at, row.machine_code), reverse=True)
    return tuple(rows)


@beartype
def _sort_at_for_cycle(cycle: MicromarketLoadingCycle, *, tz: ZoneInfo) -> datetime:
    day = cycle.opened_operational_day
    if day is None:
        return datetime.min.replace(tzinfo=UTC)
    return datetime.combine(day, time(12, 0), tzinfo=tz)
