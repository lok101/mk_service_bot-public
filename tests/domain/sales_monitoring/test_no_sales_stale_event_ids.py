from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId, MachineId
from src.domain.sales_monitoring.event_ids import (
    no_sales_stale_cleared_event_id,
    no_sales_stale_opened_event_id,
)

_MACHINE = MachineId("101")
_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_no_sales_stale_opened_event_id_format() -> None:
    """happy: opened id включает machine + opened_at."""
    assert no_sales_stale_opened_event_id(machine_id=_MACHINE, opened_at=_AT) == EventId(
        f"sales-monitoring-no-sales-stale-opened:101:{_AT.isoformat()}"
    )


def test_no_sales_stale_cleared_event_id_format() -> None:
    """happy: cleared id включает machine + cleared_at."""
    assert no_sales_stale_cleared_event_id(machine_id=_MACHINE, cleared_at=_AT) == EventId(
        f"sales-monitoring-no-sales-stale-cleared:101:{_AT.isoformat()}"
    )
