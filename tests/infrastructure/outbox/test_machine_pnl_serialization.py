from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.infrastructure.mongodb.machine_pnl_serialization import MACHINE_PNL_AGGREGATE_TYPE
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)

_PERIOD_ID = "period-1"
_SESSION_ID = "tech-1:inv-1"
_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_machine_period_pnl_requested_outbox_roundtrip() -> None:
    event = MachinePeriodPnlRequested(
        event_id=EventId(f"machine_pnl:{_PERIOD_ID}"),
        period_id=_PERIOD_ID,
        source_session_id=_SESSION_ID,
        occurred_at=_NOW,
    )
    assert event.event_id.value == f"machine_pnl:{_PERIOD_ID}"

    document = event_to_outbox_document(event)
    assert document["aggregate_type"] == MACHINE_PNL_AGGREGATE_TYPE
    assert document["event_id"] == f"machine_pnl:{_PERIOD_ID}"
    assert document["payload"]["period_id"] == _PERIOD_ID
    assert document["payload"]["source_session_id"] == _SESSION_ID

    restored = event_from_outbox_document(document)
    assert restored == event
