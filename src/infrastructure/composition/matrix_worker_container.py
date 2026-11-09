from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime


@beartype
@dataclass
class MatrixWorkerContainer:
    """Standalone composition root for matrix-worker (no AppContainer runtime)."""

    runtime: MatrixWorkerRuntime
    persistence: PersistenceBundle
    extra_closers: tuple[Callable[[], None], ...] = field(default_factory=tuple)

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> MatrixWorkerContainer:
        from src.infrastructure.composition.wiring.assemble_matrix_worker import (
            assemble_matrix_worker,
        )

        return assemble_matrix_worker(settings)

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
