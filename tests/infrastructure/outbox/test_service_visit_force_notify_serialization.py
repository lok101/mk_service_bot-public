from __future__ import annotations

from datetime import UTC, datetime

from src.application.service_visits import VisitForceOutcome
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.service_visits import (
    ServiceVisitForceNotifyRequested,
    visit_force_notify_event_id,
)
from src.infrastructure.outbox.serialization import (
    event_from_outbox_document,
    event_to_outbox_document,
)


def test_force_notify_event_roundtrip() -> None:
    """happy: force notify event survives outbox document roundtrip."""
    occurred = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    event = ServiceVisitForceNotifyRequested(
        event_id=EventId(visit_force_notify_event_id("extra:101", occurred.isoformat())),
        visit_id="extra:101",
        machine_id=MachineId("101"),
        technician_id=TechnicianId("tech-1"),
        technician_display="Иван",
        telegram_user_id=42,
        outcome=VisitForceOutcome.CREATED_EXTRA.value,
        incident_source="no_sales",
        machine_display="Аппарат 101",
        location_display="БЦ Север",
        occurred_at=occurred,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert isinstance(restored, ServiceVisitForceNotifyRequested)
    assert restored == event


def test_force_notify_event_roundtrip_without_telegram() -> None:
    """edge: telegram_user_id None preserved."""
    occurred = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    event = ServiceVisitForceNotifyRequested(
        event_id=EventId(visit_force_notify_event_id("extra:101", "g1")),
        visit_id="extra:101",
        machine_id=MachineId("101"),
        technician_id=TechnicianId("tech-1"),
        technician_display="Иван",
        telegram_user_id=None,
        outcome=VisitForceOutcome.CREATED_EXTRA.value,
        incident_source=None,
        machine_display=None,
        location_display=None,
        occurred_at=occurred,
    )
    restored = event_from_outbox_document(event_to_outbox_document(event))
    assert isinstance(restored, ServiceVisitForceNotifyRequested)
    assert restored.telegram_user_id is None
    assert restored.machine_display is None
