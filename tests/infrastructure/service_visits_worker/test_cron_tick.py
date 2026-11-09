from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.sweep_offline_extras import SweepOpenOfflineExtras
from src.application.service_visits.visit_ids import offline_incident_visit_id, scheduled_visit_id
from src.domain.ids import EventId, MachineId
from src.infrastructure.service_visits_worker.cron_scheduler import (
    build_materialize_cron_spec,
)
from src.infrastructure.service_visits_worker.cron_tick import (
    maybe_run_catch_up,
    run_service_visits_tick,
)

_MACHINE = MachineId("101")
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
_TZ = ZoneInfo("UTC")


def _materialize(store: InMemoryServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=6,
    )


class _Status:
    def __init__(self) -> None:
        self.last_materialized_operational_day: date | None = None

    def mark_materialized(self, day: date) -> None:
        self.last_materialized_operational_day = day


def test_catch_up_materializes_when_current_day_not_done() -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()
    run_service_visits_tick(
        due_date=_WED,
        store=store,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
        now=_NOW,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is not None
    assert status.last_materialized_operational_day == _WED


def test_run_service_visits_tick_logs_retrospective_counter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()

    with caplog.at_level(logging.INFO):
        run_service_visits_tick(
            due_date=_WED,
            store=store,
            catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
            materialize=_materialize(store),
            sweep=SweepOpenOfflineExtras(store=store),
            status=status,
            now=_NOW,
        )

    assert "retrospectively_closed=0" in caplog.text


def test_run_service_visits_tick_sweeps_offline_before_materialize(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryServiceVisitStore()
    extra_id = offline_incident_visit_id(EventId("off-tick"))
    store.upsert(
        ServiceVisit(
            visit_id=extra_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=date(2026, 8, 11),
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
    status = _Status()
    with caplog.at_level(logging.INFO):
        run_service_visits_tick(
            due_date=_WED,
            store=store,
            catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
            materialize=_materialize(store),
            sweep=SweepOpenOfflineExtras(store=store),
            status=status,
            now=_NOW,
        )
    extra = store.get(extra_id)
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert extra is not None and extra.status is VisitStatus.CLEARED
    assert slot is not None and slot.priority_boost is False
    assert status.last_materialized_operational_day == _WED
    assert "service_visit_offline_extra_sweep" in caplog.text


def test_catch_up_skips_when_current_day_already_materialized() -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()
    status.last_materialized_operational_day = _WED
    maybe_run_catch_up(
        now=_NOW,
        timezone=_TZ,
        end_hour=6,
        store=store,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is None
    assert status.last_materialized_operational_day == _WED


def test_catch_up_runs_when_last_materialized_is_none() -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()
    maybe_run_catch_up(
        now=_NOW,
        timezone=_TZ,
        end_hour=6,
        store=store,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is not None
    assert status.last_materialized_operational_day == _WED


def test_cron_uses_service_day_end_hour() -> None:
    spec = build_materialize_cron_spec(
        end_hour=6,
        timezone=ZoneInfo("Asia/Yekaterinburg"),
    )
    assert spec.hour == 6
    assert spec.minute == 0
    assert spec.timezone.key == "Asia/Yekaterinburg"


def test_empty_catalog_does_not_mark_materialized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()
    with caplog.at_level(logging.WARNING):
        run_service_visits_tick(
            due_date=_WED,
            store=store,
            catalog=(),
            materialize=_materialize(store),
            sweep=SweepOpenOfflineExtras(store=store),
            status=status,
            now=_NOW,
        )
    assert status.last_materialized_operational_day is None
    assert any(
        "empty" in r.message.lower() or "catalog" in r.message.lower() for r in caplog.records
    )


def test_catch_up_recovers_after_empty_catalog() -> None:
    store = InMemoryServiceVisitStore()
    status = _Status()
    run_service_visits_tick(
        due_date=_WED,
        store=store,
        catalog=(),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
        now=_NOW,
    )
    assert status.last_materialized_operational_day is None
    maybe_run_catch_up(
        now=_NOW,
        timezone=_TZ,
        end_hour=6,
        store=store,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
    )
    assert status.last_materialized_operational_day == _WED
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is not None


def test_tick_cancels_open_scheduled_for_unassigned() -> None:
    # happy / deploy orphan: open scheduled на unassigned снимается тиком
    store = InMemoryServiceVisitStore()
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    status = _Status()
    run_service_visits_tick(
        due_date=_WED,
        store=store,
        catalog=(),
        unassigned_machine_ids=(_MACHINE,),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
        now=_NOW,
    )
    assert store.get(visit_id) is None


def test_tick_materializes_assigned_catalog() -> None:
    # happy: assigned каталог по-прежнему materialize
    store = InMemoryServiceVisitStore()
    status = _Status()
    run_service_visits_tick(
        due_date=_WED,
        store=store,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        unassigned_machine_ids=(),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=status,
        now=_NOW,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is not None
    assert status.last_materialized_operational_day == _WED


def test_tick_does_not_clear_extra_on_unassigned() -> None:
    # edge: NO_SALES extra не гасится cancel-path (sweep чистит только OFFLINE)
    store = InMemoryServiceVisitStore()
    extra_id = offline_incident_visit_id(EventId("off-unassigned"))
    store.upsert(
        ServiceVisit(
            visit_id=extra_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=_WED,
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
    run_service_visits_tick(
        due_date=_WED,
        store=store,
        catalog=(),
        unassigned_machine_ids=(_MACHINE,),
        materialize=_materialize(store),
        sweep=SweepOpenOfflineExtras(store=store),
        status=_Status(),
        now=_NOW,
    )
    extra = store.get(extra_id)
    assert extra is not None
    assert extra.status is VisitStatus.OPEN
