from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.service_visits_worker.worker_runtime import ServiceVisitsWorkerRuntime


@beartype
@dataclass
class ServiceVisitsWorkerContainer:
    """Standalone composition root for service-visits-worker (no AppContainer)."""

    runtime: ServiceVisitsWorkerRuntime
    persistence: PersistenceBundle
    extra_closers: tuple[Callable[[], None], ...] = field(default_factory=tuple)

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> ServiceVisitsWorkerContainer:
        from src.infrastructure.composition.wiring.assemble_service_visits_worker import (
            assemble_service_visits_worker,
        )

        return assemble_service_visits_worker(settings)

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
