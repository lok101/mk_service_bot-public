from __future__ import annotations

from datetime import UTC, datetime

from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.domain.technician_settlement.portion_events import SettlementPortionReconcileRequested
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher

_MOMENT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_publisher_passes_not_before_for_reconcile_event() -> None:
    # happy: reconcile event with not_before set — store entry carries it
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    publisher.subscribe(SettlementPortionReconcileRequested, "settlement_portion_reconcile")
    not_before = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    event = SettlementPortionReconcileRequested(
        event_id=EventId("portion:t1:inv1:reconcile"),
        technician_id=TechnicianId("t1"),
        warehouse_inventory_id="inv1",
        warehouse_inventory_moment=_MOMENT,
        occurred_at=_MOMENT,
        not_before=not_before,
    )

    publisher.publish(event)

    entry = next(iter(store._entries.values()))
    assert entry["not_before"] == not_before


def test_publisher_omits_not_before_for_events_without_attribute() -> None:
    # regression: event type without not_before attribute — store entry gets None
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    publisher.subscribe(RevisionCompleted, "revision_inventory")
    event = RevisionCompleted(
        event_id=EventId("event-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        completed_at=_MOMENT,
        occurred_at=_MOMENT,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    publisher.publish(event)

    entry = next(iter(store._entries.values()))
    assert entry["not_before"] is None
