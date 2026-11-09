from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.domain.ids import MachineId
from src.domain.sales_monitoring.event_ids import (
    offline_cleared_event_id,
    offline_opened_event_id,
)
from src.domain.sales_monitoring.events import (
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
)


@beartype
@dataclass(frozen=True, slots=True)
class MachineOfflineInput:
    machine_id: MachineId
    kit_id: int | None
    is_offline: bool
    open_opened_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class OfflineLifecycleDecision:
    opened: tuple[SalesMonitoringOfflineOpened, ...]
    cleared: tuple[SalesMonitoringOfflineCleared, ...]
    unresolved_machine_ids: tuple[MachineId, ...]


@beartype
def decide_offline_lifecycle(
    *,
    machines: Sequence[MachineOfflineInput],
    now: datetime,
) -> OfflineLifecycleDecision:
    """Pure open/clear decisions for catalog machines (already minus excluded)."""
    opened: list[SalesMonitoringOfflineOpened] = []
    cleared: list[SalesMonitoringOfflineCleared] = []
    unresolved: list[MachineId] = []

    for machine in machines:
        if machine.kit_id is None:
            unresolved.append(machine.machine_id)
            continue

        if machine.is_offline and machine.open_opened_at is None:
            event_id = offline_opened_event_id(
                machine_id=machine.machine_id,
                opened_at=now,
            )
            opened.append(
                SalesMonitoringOfflineOpened(
                    event_id=event_id,
                    machine_id=machine.machine_id,
                    opened_at=now,
                    occurred_at=now,
                    assigned_technician_id=None,
                    assigned_technician_display=None,
                    last_serviced_by_technician_id=None,
                    last_serviced_by_display=None,
                    last_serviced_at=None,
                )
            )
            continue

        if (not machine.is_offline) and machine.open_opened_at is not None:
            opened_at = machine.open_opened_at
            opened_event_id = offline_opened_event_id(
                machine_id=machine.machine_id,
                opened_at=opened_at,
            )
            cleared.append(
                SalesMonitoringOfflineCleared(
                    event_id=offline_cleared_event_id(
                        machine_id=machine.machine_id,
                        cleared_at=now,
                    ),
                    machine_id=machine.machine_id,
                    opened_event_id=opened_event_id,
                    opened_at=opened_at,
                    cleared_at=now,
                    occurred_at=now,
                    assigned_technician_id=None,
                    assigned_technician_display=None,
                    last_serviced_by_technician_id=None,
                    last_serviced_by_display=None,
                    last_serviced_at=None,
                )
            )

    return OfflineLifecycleDecision(
        opened=tuple(opened),
        cleared=tuple(cleared),
        unresolved_machine_ids=tuple(unresolved),
    )
