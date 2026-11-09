from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.outbox.handler_ids import (
    SALES_MONITORING_AUDIT_HANDLER_ID as OUTBOX_AUDIT_HANDLER_ID,
)
from src.application.sales_monitoring.last_maintenance import LastMaintenanceSnapshot
from src.application.sales_monitoring.ports import KitMachineOfflineStatus
from src.application.sales_monitoring.run_offline_poll import (
    SALES_MONITORING_AUDIT_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
    RunOfflinePoll,
    drain_handler_until_empty,
)
from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId
from src.domain.sales_monitoring.events import SalesMonitoringOfflineOpened
from src.infrastructure.mongodb.sales_monitoring_audit_documents import offline_audit_document_id
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE_A = MachineId("101")
_MACHINE_B = MachineId("102")
_TECH = TechnicianId("t-1")
_NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)


@dataclass
class _FakeKitStates:
    by_code: dict[str, tuple[int | None, bool]]

    def statuses_for(
        self,
        *,
        machine_codes: Sequence[str],
        now: datetime,
        threshold_minutes: int,
    ) -> tuple[KitMachineOfflineStatus, ...]:
        del now, threshold_minutes
        return tuple(
            KitMachineOfflineStatus(
                machine_code=code,
                kit_id=self.by_code.get(code, (None, True))[0],
                is_offline=self.by_code.get(code, (None, True))[1],
            )
            for code in machine_codes
        )


@dataclass
class _FakePublisher:
    events: list[DomainEvent] = field(default_factory=list)

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _FakeDrainer:
    publisher: _FakePublisher
    audit: InMemorySalesMonitoringAuditStore
    calls: list[str] = field(default_factory=list)
    batch_sizes: list[int] = field(default_factory=lambda: [1])

    def drain_handler(self, handler_id: str) -> int:
        self.calls.append(handler_id)
        if not self.batch_sizes:
            return 0
        drained = self.batch_sizes.pop(0)
        if drained > 0:
            for event in self.publisher.events:
                self.audit.upsert_from_event(event)
        return drained


@dataclass
class _FakeAlertNotifier:
    unresolved: list[tuple[str, ...]] = field(default_factory=list)

    def notify_unresolved_kit_ids(self, codes: Sequence[str]) -> None:
        self.unresolved.append(tuple(codes))


@dataclass
class _FakeLastMaintenance:
    by_machine: dict[MachineId, LastMaintenanceSnapshot] = field(default_factory=dict)

    def get(self, machine_id: MachineId) -> LastMaintenanceSnapshot | None:
        return self.by_machine.get(machine_id)


@dataclass
class _FakeDisplayLookup:
    names: dict[TechnicianId, str] = field(default_factory=dict)

    def display_name(self, technician_id: TechnicianId) -> str | None:
        return self.names.get(technician_id)


def test_sales_monitoring_audit_handler_id_matches_outbox_canon() -> None:
    assert SALES_MONITORING_AUDIT_HANDLER_ID == OUTBOX_AUDIT_HANDLER_ID


def test_offline_poll_publishes_open_and_drains_audit() -> None:
    publisher = _FakePublisher()
    audit = InMemorySalesMonitoringAuditStore()
    drainer = _FakeDrainer(publisher=publisher, audit=audit)
    alert = _FakeAlertNotifier()
    kit = _FakeKitStates(by_code={"101": (1001, True)})

    use_case = RunOfflinePoll(
        kit_states=kit,
        audit_store=audit,
        publisher=publisher,
        drainer=drainer,
        alert_notifier=alert,
    )
    unresolved = use_case.execute(
        catalog_machine_ids=(_MACHINE_A,),
        excluded_codes=frozenset(),
        now=_NOW,
        threshold_minutes=25,
    )

    assert unresolved == ()
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], SalesMonitoringOfflineOpened)
    assert publisher.events[0].machine_id == _MACHINE_A
    assert drainer.calls == [
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SERVICE_VISIT_INCIDENT_HANDLER_ID,
    ]
    assert alert.unresolved == []
    open_docs = audit.list_open_offline()
    assert len(open_docs) == 1
    assert open_docs[0]["_id"] == offline_audit_document_id(_MACHINE_A)


def test_offline_poll_drains_until_empty() -> None:
    publisher = _FakePublisher()
    audit = InMemorySalesMonitoringAuditStore()
    drainer = _FakeDrainer(publisher=publisher, audit=audit, batch_sizes=[2, 1])
    use_case = RunOfflinePoll(
        kit_states=_FakeKitStates(by_code={"101": (1001, True)}),
        audit_store=audit,
        publisher=publisher,
        drainer=drainer,
        alert_notifier=_FakeAlertNotifier(),
    )
    use_case.execute(
        catalog_machine_ids=(_MACHINE_A,),
        excluded_codes=frozenset(),
        now=_NOW,
        threshold_minutes=25,
    )
    assert drainer.calls == [
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SERVICE_VISIT_INCIDENT_HANDLER_ID,
    ]
    assert audit.list_open_offline()


def test_drain_handler_until_empty_raises_when_max_rounds_exceeded() -> None:
    publisher = _FakePublisher()
    audit = InMemorySalesMonitoringAuditStore()
    # Always returns >0 → never empties within max_rounds
    drainer = _FakeDrainer(publisher=publisher, audit=audit, batch_sizes=[1, 1, 1])
    with pytest.raises(RuntimeError, match="did not empty after 2 rounds"):
        drain_handler_until_empty(drainer, SALES_MONITORING_AUDIT_HANDLER_ID, max_rounds=2)
    assert len(drainer.calls) == 2


def test_unresolved_kit_id_skips_open_and_alerts() -> None:
    publisher = _FakePublisher()
    audit = InMemorySalesMonitoringAuditStore()
    drainer = _FakeDrainer(publisher=publisher, audit=audit)
    alert = _FakeAlertNotifier()
    kit = _FakeKitStates(by_code={"102": (None, True)})

    use_case = RunOfflinePoll(
        kit_states=kit,
        audit_store=audit,
        publisher=publisher,
        drainer=drainer,
        alert_notifier=alert,
    )
    unresolved = use_case.execute(
        catalog_machine_ids=(_MACHINE_B,),
        excluded_codes=frozenset(),
        now=_NOW,
        threshold_minutes=25,
    )

    assert unresolved == (_MACHINE_B,)
    assert publisher.events == []
    assert alert.unresolved == [("102",)]
    assert drainer.calls == []
    assert not any(isinstance(event, SalesMonitoringOfflineOpened) for event in publisher.events)


def test_offline_poll_opened_carries_assigned_and_last_serviced() -> None:
    """happy: offline open несёт assigned + last_serviced snapshots."""
    last_at = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    publisher = _FakePublisher()
    audit = InMemorySalesMonitoringAuditStore()
    drainer = _FakeDrainer(publisher=publisher, audit=audit)
    use_case = RunOfflinePoll(
        kit_states=_FakeKitStates(by_code={"101": (1001, True)}),
        audit_store=audit,
        publisher=publisher,
        drainer=drainer,
        alert_notifier=_FakeAlertNotifier(),
    )
    use_case.execute(
        catalog_machine_ids=(_MACHINE_A,),
        excluded_codes=frozenset(),
        now=_NOW,
        threshold_minutes=25,
        assigned_by_machine={_MACHINE_A: (_TECH, "Иван")},
        last_maintenance=_FakeLastMaintenance(
            by_machine={
                _MACHINE_A: LastMaintenanceSnapshot(
                    technician_id=TechnicianId("t-last"),
                    completed_at=last_at,
                ),
            },
        ),
        technician_display=_FakeDisplayLookup(names={TechnicianId("t-last"): "Сергей"}),
    )
    opened = next(
        event for event in publisher.events if isinstance(event, SalesMonitoringOfflineOpened)
    )
    assert opened.assigned_technician_id == _TECH
    assert opened.assigned_technician_display == "Иван"
    assert opened.last_serviced_by_technician_id == TechnicianId("t-last")
    assert opened.last_serviced_by_display == "Сергей"
    assert opened.last_serviced_at == last_at
    offline_docs = [doc for doc in audit._documents.values() if doc.get("kind") == "offline"]
    assert offline_docs
    assert offline_docs[0]["assigned_technician_display"] == "Иван"
    assert offline_docs[0]["last_serviced_by_display"] == "Сергей"
