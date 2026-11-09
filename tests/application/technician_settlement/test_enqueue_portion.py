from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.application.technician_settlement.enqueue_portion import enqueue_portion_reconcile
from src.domain.events import DomainEvent
from src.domain.ids import TechnicianId
from src.domain.technician_settlement.portion_events import SettlementPortionReconcileRequested

_TECH = TechnicianId("t1")
_MOMENT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _CapturingPublisher:
    events: list[DomainEvent] = field(default_factory=list)

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def test_enqueue_portion_reconcile_passes_not_before_through() -> None:
    # happy: explicit not_before is forwarded onto the event unchanged
    publisher = _CapturingPublisher()
    not_before = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    enqueue_portion_reconcile(
        publisher=publisher,
        technician_id=_TECH,
        warehouse_inventory_id="inv1",
        warehouse_inventory_moment=_MOMENT,
        not_before=not_before,
    )

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, SettlementPortionReconcileRequested)
    assert event.not_before == not_before


def test_enqueue_portion_reconcile_defaults_not_before_to_none() -> None:
    # edge / regression: no not_before passed — event.not_before stays None
    publisher = _CapturingPublisher()

    enqueue_portion_reconcile(
        publisher=publisher,
        technician_id=_TECH,
        warehouse_inventory_id="inv1",
        warehouse_inventory_moment=_MOMENT,
    )

    event = publisher.events[0]
    assert isinstance(event, SettlementPortionReconcileRequested)
    assert event.not_before is None
