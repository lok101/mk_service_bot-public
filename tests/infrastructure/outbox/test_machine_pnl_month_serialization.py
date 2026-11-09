from __future__ import annotations

from datetime import UTC, date, datetime

from src.domain.ids import EventId
from src.domain.machine_pnl.events import MachineMonthPnlRequested
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)


def test_month_event_serde_roundtrip() -> None:
    event = MachineMonthPnlRequested(
        event_id=EventId("machine_pnl_month:period-1"),
        machine_id="101",
        period_start_dates=(date(2026, 5, 1), date(2026, 6, 1)),
        source_period_id="period-1",
        occurred_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    doc = event_to_outbox_document(event)
    restored = event_from_outbox_document(doc)
    assert isinstance(restored, MachineMonthPnlRequested)
    assert restored.event_id.value == "machine_pnl_month:period-1"
    assert restored.machine_id == "101"
    assert restored.period_start_dates == (date(2026, 5, 1), date(2026, 6, 1))
