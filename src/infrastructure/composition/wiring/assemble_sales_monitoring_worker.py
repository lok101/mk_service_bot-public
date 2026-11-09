from __future__ import annotations

from beartype import beartype

from src.config.settings import (
    Settings,
    get_settings,
    validate_sales_monitoring_worker_settings,
)
from src.infrastructure.composition.sales_monitoring_worker_container import (
    SalesMonitoringWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence
from src.infrastructure.composition.wiring.wire_sales_monitoring_worker import (
    wire_sales_monitoring_worker,
)


@beartype
def assemble_sales_monitoring_worker(
    settings: Settings | None = None,
) -> SalesMonitoringWorkerContainer:
    resolved = settings or get_settings()
    validate_sales_monitoring_worker_settings(resolved)
    persistence = wire_persistence(resolved)
    return wire_sales_monitoring_worker(resolved, persistence=persistence)
