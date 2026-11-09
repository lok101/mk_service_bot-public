from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.daily_sales_demand.worker_runtime import DailySalesDemandWorkerRuntime
from src.infrastructure.outbox.processor import OutboxProcessorRegistry


@beartype
@dataclass
class DailySalesDemandWorkerContainer:
    """Standalone composition root for daily-sales-demand-worker (no AppContainer)."""

    runtime: DailySalesDemandWorkerRuntime
    persistence: PersistenceBundle
    extra_closers: tuple[Callable[[], None], ...] = field(default_factory=tuple)
    outbox_processors: OutboxProcessorRegistry | None = None

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> DailySalesDemandWorkerContainer:
        from src.infrastructure.composition.wiring.assemble_daily_sales_demand_worker import (
            assemble_daily_sales_demand_worker,
        )

        return assemble_daily_sales_demand_worker(settings)

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
