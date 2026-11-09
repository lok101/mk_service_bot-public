from __future__ import annotations

from datetime import UTC, date, datetime

from src.domain.ids import EventId, MachineId
from src.domain.sales_monitoring.event_ids import (
    offline_cleared_event_id,
    offline_opened_event_id,
    sales_finding_event_id,
)
from src.domain.sales_monitoring.events import (
    SalesMonitoringYesterdayNoSales,
)


def test_sales_finding_event_id_format() -> None:
    eid = sales_finding_event_id(
        event_type="SalesMonitoringYesterdayNoSales",
        machine_id=MachineId("m-1"),
        report_day=date(2026, 7, 27),
    )
    assert eid.value == "SalesMonitoringYesterdayNoSales:m-1:2026-07-27"


def test_offline_open_event_id_includes_opened_at() -> None:
    opened_at = datetime(2026, 7, 27, 9, 15, 30, tzinfo=UTC)
    eid = offline_opened_event_id(machine_id=MachineId("m-1"), opened_at=opened_at)
    assert eid.value == "sales-monitoring-offline-opened:m-1:2026-07-27T09:15:30+00:00"


def test_offline_cleared_event_id_format() -> None:
    cleared_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    eid = offline_cleared_event_id(machine_id=MachineId("m-1"), cleared_at=cleared_at)
    assert eid.value == "sales-monitoring-offline-cleared:m-1:2026-07-27T10:00:00+00:00"


def test_yesterday_no_sales_event_carries_snapshots_nullable() -> None:
    event = SalesMonitoringYesterdayNoSales(
        event_id=EventId("SalesMonitoringYesterdayNoSales:m-1:2026-07-27"),
        machine_id=MachineId("m-1"),
        report_day=date(2026, 7, 27),
        occurred_at=datetime(2026, 7, 28, 8, 0, tzinfo=UTC),
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    assert event.assigned_technician_id is None
