from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.sales_monitoring.worker_runtime import SalesMonitoringWorkerRuntime


@beartype
@dataclass
class SalesMonitoringWorkerContainer:
    """Standalone composition root for sales-monitoring-worker (no AppContainer runtime)."""

    runtime: SalesMonitoringWorkerRuntime
    persistence: PersistenceBundle
    extra_closers: tuple[Callable[[], None], ...] = field(default_factory=tuple)
    outbox_processors: OutboxProcessorRegistry | None = None

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> SalesMonitoringWorkerContainer:
        from src.infrastructure.composition.wiring.assemble_sales_monitoring_worker import (
            assemble_sales_monitoring_worker,
        )

        return assemble_sales_monitoring_worker(settings)

    @beartype
    async def run(self) -> None:
        await self.runtime.run()

    @beartype
    def request_shutdown(self) -> None:
        self.runtime.request_shutdown()

    @beartype
    def close(self) -> None:
        try:
            for closer in self.extra_closers:
                closer()
        finally:
            if self.persistence.mongo_client is not None:
                self.persistence.mongo_client.close()
            if self.persistence.redis_client is not None:
                self.persistence.redis_client.close()
