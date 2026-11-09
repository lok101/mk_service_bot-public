from __future__ import annotations

from beartype import beartype

from src.config.settings import (
    Settings,
    get_settings,
    validate_machine_pnl_month_worker_settings,
)
from src.infrastructure.composition.machine_pnl_month_worker_container import (
    MachinePnlMonthWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_machine_pnl_month_worker import (
    wire_machine_pnl_month_worker,
)
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence


@beartype
def assemble_machine_pnl_month_worker(
    settings: Settings | None = None,
) -> MachinePnlMonthWorkerContainer:
    resolved = settings or get_settings()
    validate_machine_pnl_month_worker_settings(resolved)
    persistence = wire_persistence(resolved)
    return wire_machine_pnl_month_worker(resolved, persistence=persistence)
