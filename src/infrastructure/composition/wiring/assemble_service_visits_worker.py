from __future__ import annotations

from beartype import beartype

from src.config.settings import (
    Settings,
    get_settings,
    validate_service_visits_worker_settings,
)
from src.infrastructure.composition.service_visits_worker_container import (
    ServiceVisitsWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence
from src.infrastructure.composition.wiring.wire_service_visits_worker import (
    wire_service_visits_worker,
)


@beartype
def assemble_service_visits_worker(
    settings: Settings | None = None,
) -> ServiceVisitsWorkerContainer:
    resolved = settings or get_settings()
    validate_service_visits_worker_settings(resolved)
    persistence = wire_persistence(resolved)
    return wire_service_visits_worker(resolved, persistence=persistence)
