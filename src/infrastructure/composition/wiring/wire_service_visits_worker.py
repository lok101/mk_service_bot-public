from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.reference_data import ReferenceDataProvider
from src.application.service_visits import (
    MachineSchedule,
    MaterializeScheduledVisits,
    SweepOpenOfflineExtras,
)
from src.config.settings import Settings
from src.domain.calendar import operational_day
from src.domain.ids import MachineId
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import (
    attach_location_roster,
    attach_master_data,
    attach_technicians,
    build_event_store,
    build_location_roster_store,
    build_maintenance_on_operational_day_lookup,
    build_master_data_stores,
    build_reference_data_snapshot_store,
    build_reference_data_sync,
    build_service_visit_store,
    build_technician_store,
    warm_up_reference_data_provider,
)
from src.infrastructure.composition.service_visits_worker_container import (
    ServiceVisitsWorkerContainer,
)
from src.infrastructure.service_visits_worker.cron_scheduler import ServiceVisitsCronScheduler
from src.infrastructure.service_visits_worker.cron_tick import (
    maybe_run_catch_up,
    run_service_visits_tick,
    tick_inputs_from_provider,
)
from src.infrastructure.service_visits_worker.mongo_worker_status import (
    MongoServiceVisitsWorkerStatusRepository,
)
from src.infrastructure.service_visits_worker.worker_runtime import ServiceVisitsWorkerRuntime

_LOGGER = logging.getLogger(__name__)


@beartype
class _SystemUtcClock:
    def now_utc_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@beartype
class _InMemoryWorkerStatusRepository:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []
        self._last_materialized_operational_day: date | None = None

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))

    def mark_materialized(self, day: date) -> None:
        self._last_materialized_operational_day = day

    @property
    def last_materialized_operational_day(self) -> date | None:
        return self._last_materialized_operational_day


@beartype
def wire_service_visits_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
) -> ServiceVisitsWorkerContainer:
    enabled = settings.service_visits.worker_enabled
    mongo_client = persistence.mongo_client
    timezone: ZoneInfo = settings.service_calendar.zone_info()
    end_hour = settings.service_calendar.service_day_end_hour

    if enabled and (mongo_client is None or not settings.mongodb.is_configured):
        raise ValueError(
            "SERVICE_VISITS_WORKER_ENABLED=true requires a configured MongoDB client",
        )

    if mongo_client is not None and settings.mongodb.is_configured:
        status_repository: (
            MongoServiceVisitsWorkerStatusRepository | _InMemoryWorkerStatusRepository
        ) = MongoServiceVisitsWorkerStatusRepository.from_settings(
            settings.mongodb,
            collection_name=settings.service_visits.worker_status_collection,
            client=mongo_client,
        )
    else:
        status_repository = _InMemoryWorkerStatusRepository()

    extra_closers: tuple[Callable[[], None], ...] = ()
    on_start: Callable[[], None] | None = None

    if enabled:
        assert mongo_client is not None
        event_store = build_event_store(settings, client=mongo_client)
        visit_store = build_service_visit_store(settings, client=mongo_client)
        maintenance_lookup = build_maintenance_on_operational_day_lookup(event_store)
        materialize = MaterializeScheduledVisits(
            store=visit_store,
            maintenance_lookup=maintenance_lookup,
            timezone=timezone,
            day_end_hour=end_hour,
        )
        sweep = SweepOpenOfflineExtras(store=visit_store)
        reference_store = build_reference_data_snapshot_store(settings, client=mongo_client)
        provider = ReferenceDataProvider()
        reference_sync = build_reference_data_sync(
            settings,
            store=reference_store,
            provider=provider,
        )
        warm_up_reference_data_provider(
            provider=provider,
            store=reference_store,
            sync=reference_sync,
        )
        roster_store = build_location_roster_store(settings, client=mongo_client)
        attach_location_roster(
            provider,
            settings,
            roster_store=roster_store,
            snapshot_store=reference_store,
            now=datetime.now(UTC),
        )
        master_data_stores = build_master_data_stores(settings, mongo_client=mongo_client)
        attach_master_data(
            provider,
            stores=master_data_stores,
            enabled=settings.master_data.enabled,
        )
        technician_store = build_technician_store(settings, mongo_client=mongo_client)
        attach_technicians(
            provider,
            store=technician_store,
            enabled=settings.master_data.technicians_enabled,
        )

        def _load_tick_inputs() -> tuple[
            tuple[MachineSchedule, ...],
            tuple[MachineId, ...],
        ]:
            try:
                warm_up_reference_data_provider(
                    provider=provider,
                    store=reference_store,
                    sync=reference_sync,
                )
            except Exception:
                # Sheets sync must not block master_data + roster overlay materialize.
                _LOGGER.exception("service_visits_tick_warm_up_failed")
            attach_master_data(
                provider,
                stores=master_data_stores,
                enabled=settings.master_data.enabled,
            )
            attach_technicians(
                provider,
                store=technician_store,
                enabled=settings.master_data.technicians_enabled,
            )
            return tick_inputs_from_provider(provider)

        def cron_callback() -> None:
            try:
                now = datetime.now(timezone)
                catalog, unassigned = _load_tick_inputs()
                run_service_visits_tick(
                    due_date=operational_day(now, timezone, end_hour),
                    store=visit_store,
                    catalog=catalog,
                    unassigned_machine_ids=unassigned,
                    materialize=materialize,
                    sweep=sweep,
                    status=status_repository,
                    now=now,
                )
            except Exception:
                _LOGGER.exception("service_visits_cron_tick_failed")

        def catch_up() -> None:
            try:
                catalog, unassigned = _load_tick_inputs()
                maybe_run_catch_up(
                    now=datetime.now(timezone),
                    timezone=timezone,
                    end_hour=end_hour,
                    store=visit_store,
                    catalog=catalog,
                    unassigned_machine_ids=unassigned,
                    materialize=materialize,
                    sweep=sweep,
                    status=status_repository,
                )
            except Exception:
                _LOGGER.exception("service_visits_catch_up_failed")

        callback = cron_callback
        on_start = catch_up
    else:

        def callback() -> None:
            return None

    scheduler = ServiceVisitsCronScheduler(
        enabled=enabled,
        end_hour=end_hour,
        timezone=timezone,
        callback=callback,
    )
    runtime = ServiceVisitsWorkerRuntime(
        enabled=enabled,
        status_repository=status_repository,
        scheduler=scheduler,
        clock=_SystemUtcClock(),
        on_start=on_start,
    )
    return ServiceVisitsWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
    )


__all__ = (
    "_InMemoryWorkerStatusRepository",
    "_SystemUtcClock",
    "wire_service_visits_worker",
)
