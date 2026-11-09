from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.application.reference_data import ReferenceDataProvider
from src.config.settings import Settings
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.daily_sales_demand_worker_container import (
    DailySalesDemandWorkerContainer,
)
from src.infrastructure.composition.factories import (
    build_outbox_store,
    build_reference_data_snapshot_store,
    build_reference_data_sync,
    warm_up_reference_data_provider,
)
from src.infrastructure.daily_sales_demand.cron_scheduler import DailySalesDemandCronScheduler
from src.infrastructure.daily_sales_demand.enqueue_daily_sales_demand import (
    compute_yesterday_sales_day,
    enqueue_daily_sales_demand_for_day,
)
from src.infrastructure.daily_sales_demand.mongo_worker_status import (
    MongoDailySalesDemandWorkerStatusRepository,
)
from src.infrastructure.daily_sales_demand.worker_runtime import DailySalesDemandWorkerRuntime
from src.infrastructure.outbox import OutboxDomainEventPublisher, OutboxProcessorRegistry


@beartype
class _SystemUtcClock:
    def now_utc_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@beartype
class _InMemoryWorkerStatusRepository:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))


# Re-export for tests that monkeypatch wire module symbols.
__all__ = (
    "_InMemoryWorkerStatusRepository",
    "_SystemUtcClock",
    "wire_daily_sales_demand_worker",
)


@beartype
def wire_daily_sales_demand_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
) -> DailySalesDemandWorkerContainer:
    enabled = settings.daily_sales_demand.worker_enabled
    mongo_client = persistence.mongo_client

    if enabled and (mongo_client is None or not settings.mongodb.is_configured):
        raise ValueError(
            "DAILY_SALES_DEMAND_WORKER_ENABLED=true requires a configured MongoDB client",
        )

    if mongo_client is not None and settings.mongodb.is_configured:
        status_repository: (
            MongoDailySalesDemandWorkerStatusRepository | _InMemoryWorkerStatusRepository
        ) = MongoDailySalesDemandWorkerStatusRepository.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    else:
        status_repository = _InMemoryWorkerStatusRepository()

    clock = _SystemUtcClock()
    extra_closers: tuple[Callable[[], None], ...] = ()
    outbox_processors: OutboxProcessorRegistry | None = None
    timezone: ZoneInfo = settings.service_calendar.zone_info()
    cron_hour = settings.daily_sales_demand.cron_hour

    if enabled:
        assert mongo_client is not None
        # Enqueue-only: Remap MS write runs in effects-worker (ADR-0083).
        outbox_store = build_outbox_store(settings, client=mongo_client)
        processors = OutboxProcessorRegistry()
        publisher = OutboxDomainEventPublisher(store=outbox_store)
        publisher.subscribe(DailySalesDemandRequested, DAILY_SALES_DEMAND_HANDLER_ID)
        outbox_processors = processors

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

        def cron_callback() -> None:
            warm_up_reference_data_provider(
                provider=provider,
                store=reference_store,
                sync=reference_sync,
            )
            now = datetime.now(timezone)
            sales_day = compute_yesterday_sales_day(now=now, tz=timezone)
            enqueue_daily_sales_demand_for_day(
                outbox=outbox_store,
                sales_day=sales_day,
                occurred_at=now,
            )

        callback = cron_callback
    else:

        def callback() -> None:
            return None

    scheduler = DailySalesDemandCronScheduler(
        enabled=enabled,
        cron_hour=cron_hour,
        timezone=timezone,
        callback=callback,
    )
    runtime = DailySalesDemandWorkerRuntime(
        enabled=enabled,
        status_repository=status_repository,
        scheduler=scheduler,
        clock=clock,
    )
    return DailySalesDemandWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
        outbox_processors=outbox_processors,
    )
