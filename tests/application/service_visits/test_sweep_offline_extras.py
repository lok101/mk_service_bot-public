from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pytest

from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.sweep_offline_extras import SweepOpenOfflineExtras
from src.application.service_visits.visit_ids import offline_incident_visit_id
from src.domain.ids import EventId, MachineId

_MACHINE = MachineId("101")
_OTHER = MachineId("202")
_NOW = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
_DUE = date(2026, 8, 11)


def _offline_extra(machine_id: MachineId, suffix: str) -> ServiceVisit:
    return ServiceVisit(
        visit_id=offline_incident_visit_id(EventId(f"off-{suffix}")),
        machine_id=machine_id,
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=_DUE,
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
    )


def test_sweep_clears_open_offline_extras(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryServiceVisitStore()
    store.upsert(_offline_extra(_MACHINE, "1"))
    store.upsert(
        ServiceVisit(
            visit_id=offline_incident_visit_id(EventId("off-ns")),
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=_DUE,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.NO_SALES,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    with caplog.at_level(logging.INFO):
        result = SweepOpenOfflineExtras(store=store).execute(now=_NOW)
    offline = store.get(offline_incident_visit_id(EventId("off-1")))
    no_sales = store.get(offline_incident_visit_id(EventId("off-ns")))
    assert result.cleared_count == 1
    assert offline is not None and offline.status is VisitStatus.CLEARED
    assert offline.closable is False
    assert no_sales is not None and no_sales.status is VisitStatus.OPEN
    assert "service_visit_offline_extra_sweep cleared_count=1" in caplog.text


def test_sweep_clears_offline_extra_outside_weekday_catalog() -> None:
    """Машина не в today's catalog weekday — sweep всё равно чистит."""
    store = InMemoryServiceVisitStore()
    store.upsert(_offline_extra(_OTHER, "out"))
    result = SweepOpenOfflineExtras(store=store).execute(now=_NOW)
    extra = store.get(offline_incident_visit_id(EventId("off-out")))
    assert result.cleared_count == 1
    assert extra is not None and extra.status is VisitStatus.CLEARED
