from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId


@runtime_checkable
class ServiceFactCounter(Protocol):
    @beartype
    def count_completed(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> int: ...


@runtime_checkable
class ZeroMaintenanceAlerter(Protocol):
    @beartype
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        maintenance_count: int,
    ) -> None: ...


@runtime_checkable
class MachinePnlOpsTerminalAlerter(Protocol):
    """Ops TG on MACHINE_PNL_ALERT_CHAT_ID for terminal machine_pnl_period failures."""

    @beartype
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        period_id: str | None,
        event_id: str | None,
    ) -> None: ...
