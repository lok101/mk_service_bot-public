from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.reference_data import ReferenceDataProvider
from src.application.service_visits import (
    MachineSchedule,
    MaterializeScheduledVisits,
    ServiceVisitStore,
    SweepOpenOfflineExtras,
    cancel_open_scheduled_for_machines,
)
from src.application.sheets import TechnicianLocationsSnapshot
from src.domain.calendar import operational_day
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ServiceVisitsTickStatus(Protocol):
    def mark_materialized(self, day: date) -> None: ...

    @property
    def last_materialized_operational_day(self) -> date | None: ...


@beartype
def catalog_from_locations_snapshot(
    snapshot: TechnicianLocationsSnapshot,
) -> tuple[MachineSchedule, ...]:
    return tuple(
        MachineSchedule(machine.id, machine.service_weekdays)
        for machines in snapshot.machines_by_technician_id.values()
        for machine in machines
    )


@beartype
def tick_inputs_from_provider(
    provider: ReferenceDataProvider,
) -> tuple[tuple[MachineSchedule, ...], tuple[MachineId, ...]]:
    snapshot = provider.service_locations_or_none()
    if snapshot is None:
        _LOGGER.warning("service_visits_tick inputs skipped: service_locations unavailable")
        return (), ()
    catalog = catalog_from_locations_snapshot(snapshot)
    unassigned = tuple(machine.id for machine in snapshot.unassigned_machines)
    return catalog, unassigned


@beartype
def run_service_visits_tick(
    *,
    due_date: date,
    store: ServiceVisitStore,
    catalog: tuple[MachineSchedule, ...],
    materialize: MaterializeScheduledVisits,
    sweep: SweepOpenOfflineExtras,
    status: ServiceVisitsTickStatus,
    now: datetime,
    unassigned_machine_ids: tuple[MachineId, ...] = (),
) -> None:
    sweep_result = sweep.execute(now=now)
    cancelled = cancel_open_scheduled_for_machines(
        store,
        machine_ids=unassigned_machine_ids,
        ops_day=due_date,
    )
    if not catalog:
        _LOGGER.warning(
            "service_visits_tick skipped mark_materialized: empty catalog operational_day=%s",
            due_date.isoformat(),
        )
        return
    result = materialize.execute(due_date=due_date, catalog=catalog, now=now)
    status.mark_materialized(due_date)
    _LOGGER.info(
        "service_visits_tick operational_day=%s upserted=%s buried=%s "
        "extras_absorbed=%s retrospectively_closed=%s offline_extras_cleared=%s cancelled=%s",
        due_date.isoformat(),
        result.upserted,
        result.buried,
        result.extras_absorbed,
        result.retrospectively_closed,
        sweep_result.cleared_count,
        cancelled,
    )


@beartype
def maybe_run_catch_up(
    *,
    now: datetime,
    timezone: ZoneInfo,
    end_hour: int,
    store: ServiceVisitStore,
    catalog: tuple[MachineSchedule, ...],
    materialize: MaterializeScheduledVisits,
    sweep: SweepOpenOfflineExtras,
    status: ServiceVisitsTickStatus,
    unassigned_machine_ids: tuple[MachineId, ...] = (),
) -> None:
    today_ops = operational_day(now, timezone, end_hour)
    if status.last_materialized_operational_day == today_ops:
        return
    run_service_visits_tick(
        due_date=today_ops,
        store=store,
        catalog=catalog,
        materialize=materialize,
        sweep=sweep,
        status=status,
        now=now,
        unassigned_machine_ids=unassigned_machine_ids,
    )
