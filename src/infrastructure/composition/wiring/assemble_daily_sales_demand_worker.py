from __future__ import annotations

from beartype import beartype

from src.config.settings import (
    Settings,
    get_settings,
    validate_daily_sales_demand_worker_settings,
)
from src.infrastructure.composition.daily_sales_demand_worker_container import (
    DailySalesDemandWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_daily_sales_demand_worker import (
    wire_daily_sales_demand_worker,
)
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence


@beartype
def assemble_daily_sales_demand_worker(
    settings: Settings | None = None,
) -> DailySalesDemandWorkerContainer:
    resolved = settings or get_settings()
    validate_daily_sales_demand_worker_settings(resolved)
    persistence = wire_persistence(resolved)
    return wire_daily_sales_demand_worker(resolved, persistence=persistence)
