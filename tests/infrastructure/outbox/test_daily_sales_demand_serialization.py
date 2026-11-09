from __future__ import annotations

from datetime import UTC, date, datetime

from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.mongodb.daily_sales_demand_serialization import (
    DAILY_SALES_DEMAND_AGGREGATE_TYPE,
    daily_sales_demand_event_from_document,
    daily_sales_demand_event_to_document,
)
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)

_SALES_DAY = date(2026, 8, 9)
_NOW = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)


def test_daily_sales_demand_serde_roundtrip() -> None:
    event = DailySalesDemandRequested(
        event_id=EventId("daily_sales_demand:2026-08-09"),
        sales_day=_SALES_DAY,
        occurred_at=_NOW,
    )
    doc = daily_sales_demand_event_to_document(event, aggregate_version=0)
    assert doc["event_id"] == "daily_sales_demand:2026-08-09"
    assert doc["event_type"] == "DailySalesDemandRequested"
    assert doc["aggregate_type"] == DAILY_SALES_DEMAND_AGGREGATE_TYPE
    assert doc["aggregate_id"] == "2026-08-09"
    assert doc["payload"]["sales_day"] == "2026-08-09"
    back = daily_sales_demand_event_from_document(doc)
    assert back.sales_day == _SALES_DAY
    assert back == event


def test_outbox_serialization_routes_daily_sales_demand() -> None:
    event = DailySalesDemandRequested(
        event_id=EventId("daily_sales_demand:2026-08-09"),
        sales_day=_SALES_DAY,
        occurred_at=_NOW,
    )
    doc = event_to_outbox_document(event)
    assert isinstance(event_from_outbox_document(doc), DailySalesDemandRequested)
