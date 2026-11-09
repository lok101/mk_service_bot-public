from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.service_visits import (
    AssignedTechnicianRef,
    EnqueueVisitForceNotify,
    IncidentSource,
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.service_visits import visit_force_notify_event_id

_MACHINE = MachineId("101")
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
_GEN = "2026-08-12T08:00:00+00:00"
_TECH = TechnicianId("tech-1")


@dataclass
class _FakePublisher:
    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


@dataclass
class _NullResolver:
    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None:
        del machine_id
        return None


@dataclass
class _AlwaysAssignedResolver:
    ref: AssignedTechnicianRef

    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None:
        del machine_id
        return self.ref


def _assigned() -> AssignedTechnicianRef:
    return AssignedTechnicianRef(
        technician_id=_TECH,
        display_name="Иван",
        telegram_user_id=1001,
    )


def _created_result() -> OpenIncidentResult:
    return OpenIncidentResult(
        outcome=VisitForceOutcome.CREATED_EXTRA,
        machine_id=_MACHINE,
        visit_id="extra:101",
        generation=_GEN,
    )


def test_enqueue_force_notify_on_created_extra_assigned() -> None:
    """happy: created_extra + assigned → один event."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=True,
    )
    assert uc.execute(
        result=_created_result(),
        incident_source=IncidentSource.NO_SALES,
        occurred_at=_NOW,
        machine_display="Аппарат 101",
    )
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert event.event_id.value == visit_force_notify_event_id("extra:101", _GEN)
    assert event.technician_id == _TECH


def test_enqueue_force_notify_skips_unassigned(caplog: pytest.LogCaptureFixture) -> None:
    """edge: resolver None → no publish."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_NullResolver(),
        enabled=True,
    )
    with caplog.at_level("INFO"):
        assert not uc.execute(
            result=_created_result(),
            incident_source=IncidentSource.NO_SALES,
            occurred_at=_NOW,
        )
    assert publisher.events == []
    assert "visit_force_notify_skipped_unassigned" in caplog.text


def test_enqueue_force_notify_disabled_skips() -> None:
    """edge: enabled=False → no publish."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=False,
    )
    assert not uc.execute(
        result=_created_result(),
        incident_source=IncidentSource.NO_SALES,
        occurred_at=_NOW,
    )
    assert publisher.events == []


def test_enqueue_force_notify_idempotent_same_generation() -> None:
    """idempotency: два execute с тем же result → один и тот же event_id."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=True,
    )
    result = _created_result()
    uc.execute(result=result, incident_source=IncidentSource.NO_SALES, occurred_at=_NOW)
    uc.execute(result=result, incident_source=IncidentSource.NO_SALES, occurred_at=_NOW)
    assert len(publisher.events) == 2
    assert publisher.events[0].event_id == publisher.events[1].event_id


def test_enqueue_force_notify_reopen_new_generation() -> None:
    """happy: generation2 ≠ generation1 → разные event_id."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=True,
    )
    r1 = OpenIncidentResult(
        outcome=VisitForceOutcome.REOPENED_EXTRA,
        machine_id=_MACHINE,
        visit_id="extra:101",
        generation="2026-08-12T08:00:00+00:00",
    )
    r2 = OpenIncidentResult(
        outcome=VisitForceOutcome.REOPENED_EXTRA,
        machine_id=_MACHINE,
        visit_id="extra:101",
        generation="2026-08-13T09:00:00+00:00",
    )
    uc.execute(result=r1, incident_source=IncidentSource.NO_SALES, occurred_at=_NOW)
    uc.execute(result=r2, incident_source=IncidentSource.NO_SALES, occurred_at=_NOW)
    assert publisher.events[0].event_id != publisher.events[1].event_id


def test_enqueue_force_notify_skips_noop() -> None:
    """edge: noop outcome → no publish."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=True,
    )
    assert not uc.execute(
        result=OpenIncidentResult(
            outcome=VisitForceOutcome.NOOP,
            machine_id=_MACHINE,
            visit_id="extra:101",
            generation=_GEN,
        ),
        incident_source=IncidentSource.NO_SALES,
        occurred_at=_NOW,
    )
    assert publisher.events == []


def test_enqueue_event_id_is_event_id_type() -> None:
    """happy: published event_id is EventId."""
    publisher = _FakePublisher()
    uc = EnqueueVisitForceNotify(
        publisher=publisher,
        resolver=_AlwaysAssignedResolver(_assigned()),
        enabled=True,
    )
    uc.execute(
        result=_created_result(),
        incident_source=IncidentSource.NO_SALES,
        occurred_at=_NOW,
    )
    assert isinstance(publisher.events[0].event_id, EventId)
