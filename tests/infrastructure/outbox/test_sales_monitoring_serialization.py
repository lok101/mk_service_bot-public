from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.mongodb.sales_monitoring_serialization import (
    SALES_MONITORING_AGGREGATE_TYPE,
)
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)

_MACHINE = MachineId("vm-serde-01")
_NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
_DAY = date(2026, 7, 28)
_OPENED = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
_CLEARED = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)
_TECH = TechnicianId("tech-serde")


def test_sales_monitoring_yesterday_no_sales_outbox_roundtrip() -> None:
    event = SalesMonitoringYesterdayNoSales(
        event_id=EventId(f"SalesMonitoringYesterdayNoSales:{_MACHINE.value}:{_DAY.isoformat()}"),
        machine_id=_MACHINE,
        report_day=_DAY,
        occurred_at=_NOW,
        assigned_technician_id=_TECH,
        assigned_technician_display="Техник",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    document = event_to_outbox_document(event)
    assert document["aggregate_type"] == SALES_MONITORING_AGGREGATE_TYPE
    restored = event_from_outbox_document(document)
    assert restored == event


def test_sales_monitoring_yesterday_decline_outbox_roundtrip() -> None:
    event = SalesMonitoringYesterdayDecline(
        event_id=EventId(f"SalesMonitoringYesterdayDecline:{_MACHINE.value}:{_DAY.isoformat()}"),
        machine_id=_MACHINE,
        report_day=_DAY,
        occurred_at=_NOW,
        report_sum=Decimal("100.00"),
        baseline_avg=Decimal("200.00"),
        drop_percent=40,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=_TECH,
        last_serviced_by_display="Обслуживший",
        last_serviced_at=_OPENED,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_sales_monitoring_today_no_sales_outbox_roundtrip() -> None:
    event = SalesMonitoringTodayNoSales(
        event_id=EventId(f"SalesMonitoringTodayNoSales:{_MACHINE.value}:{_DAY.isoformat()}"),
        machine_id=_MACHINE,
        report_day=_DAY,
        occurred_at=_NOW,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_sales_monitoring_offline_opened_outbox_roundtrip() -> None:
    event = SalesMonitoringOfflineOpened(
        event_id=EventId(f"sales-monitoring-offline-opened:{_MACHINE.value}:{_OPENED.isoformat()}"),
        machine_id=_MACHINE,
        opened_at=_OPENED,
        occurred_at=_OPENED,
        assigned_technician_id=_TECH,
        assigned_technician_display="Техник",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_sales_monitoring_offline_cleared_outbox_roundtrip() -> None:
    opened_event_id = EventId(
        f"sales-monitoring-offline-opened:{_MACHINE.value}:{_OPENED.isoformat()}"
    )
    event = SalesMonitoringOfflineCleared(
        event_id=EventId(
            f"sales-monitoring-offline-cleared:{_MACHINE.value}:{_CLEARED.isoformat()}"
        ),
        machine_id=_MACHINE,
        opened_event_id=opened_event_id,
        opened_at=_OPENED,
        cleared_at=_CLEARED,
        occurred_at=_CLEARED,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_sales_monitoring_no_sales_stale_opened_outbox_roundtrip() -> None:
    last_sale_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
    event = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-opened:{_MACHINE.value}:{_OPENED.isoformat()}"
        ),
        machine_id=_MACHINE,
        opened_at=_OPENED,
        occurred_at=_OPENED,
        last_sale_at=last_sale_at,
        assigned_technician_id=_TECH,
        assigned_technician_display="Техник",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_sales_monitoring_no_sales_stale_cleared_outbox_roundtrip() -> None:
    opened_event_id = EventId(
        f"sales-monitoring-no-sales-stale-opened:{_MACHINE.value}:{_OPENED.isoformat()}"
    )
    last_sale_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    event = SalesMonitoringNoSalesStaleCleared(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-cleared:{_MACHINE.value}:{_CLEARED.isoformat()}"
        ),
        machine_id=_MACHINE,
        opened_event_id=opened_event_id,
        opened_at=_OPENED,
        cleared_at=_CLEARED,
        occurred_at=_CLEARED,
        last_sale_at=last_sale_at,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def _cleared_base(**kwargs: object) -> SalesMonitoringNoSalesStaleCleared:
    opened_event_id = EventId(
        f"sales-monitoring-no-sales-stale-opened:{_MACHINE.value}:{_OPENED.isoformat()}"
    )
    last_sale_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    base = SalesMonitoringNoSalesStaleCleared(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-cleared:{_MACHINE.value}:{_CLEARED.isoformat()}"
        ),
        machine_id=_MACHINE,
        opened_event_id=opened_event_id,
        opened_at=_OPENED,
        cleared_at=_CLEARED,
        occurred_at=_CLEARED,
        last_sale_at=last_sale_at,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
        clear_trigger=None,
        bypass_active=None,
    )
    if not kwargs:
        return base
    return replace(base, **kwargs)  # type: ignore[arg-type]


def test_cleared_payload_with_clear_fields_serde_roundtrip() -> None:
    """happy: clear_trigger и bypass_active переживают serde roundtrip."""
    event = replace(
        _cleared_base(),
        clear_trigger="sale",
        bypass_active=True,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event


def test_cleared_payload_without_clear_fields_deserializes_to_none() -> None:
    """error/legacy: payload без ключей → None, без исключения."""
    event = _cleared_base()
    document = event_to_outbox_document(event)
    payload = document["payload"]
    assert isinstance(payload, dict)
    payload.pop("clear_trigger", None)
    payload.pop("bypass_active", None)
    restored = event_from_outbox_document(document)
    assert isinstance(restored, SalesMonitoringNoSalesStaleCleared)
    assert restored.clear_trigger is None
    assert restored.bypass_active is None


def test_sales_monitoring_no_sales_stale_opened_null_last_sale_roundtrip() -> None:
    """edge: last_sale_at=None сохраняется в serde."""
    event = SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            f"sales-monitoring-no-sales-stale-opened:{_MACHINE.value}:{_OPENED.isoformat()}"
        ),
        machine_id=_MACHINE,
        opened_at=_OPENED,
        occurred_at=_OPENED,
        last_sale_at=None,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert restored == event
