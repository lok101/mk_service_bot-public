from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.closable_extra_additional_maintenance import (
    ClosableExtraAdditionalMaintenance,
)

_MACHINE = MachineId("101")
_NOW = datetime(2026, 8, 12, tzinfo=UTC)


def test_adapter_allows_when_closable_extra_open() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        ServiceVisit(
            visit_id="incident:offline:e",
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=date(2026, 8, 12),
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.OFFLINE,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    assert ClosableExtraAdditionalMaintenance(store).allows(_MACHINE, _NOW) is True


def test_adapter_denies_when_only_priority_boost() -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(
        ServiceVisit(
            visit_id="scheduled:101:2026-08-12",
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=date(2026, 8, 12),
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=True,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    assert ClosableExtraAdditionalMaintenance(store).allows(_MACHINE, _NOW) is False
