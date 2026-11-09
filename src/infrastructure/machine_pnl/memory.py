from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.application.machine_pnl import PeriodPnl
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryPeriodPnlStore:
    _by_pnl_id: dict[str, PeriodPnl] = field(default_factory=dict)
    source_session_ids: dict[str, str | None] = field(default_factory=dict)

    def save(self, pnl: PeriodPnl, *, source_session_id: str | None) -> None:
        self._by_pnl_id[pnl.pnl_id] = pnl
        self.source_session_ids[pnl.pnl_id] = source_session_id

    def get(self, pnl_id: str) -> PeriodPnl | None:
        return self._by_pnl_id.get(pnl_id)

    def list_by_period_id(self, period_id: str) -> tuple[PeriodPnl, ...]:
        return tuple(pnl for pnl in self._by_pnl_id.values() if pnl.period_id == period_id)

    def list_overlapping(
        self,
        machine_id: MachineId,
        *,
        range_start: datetime,
        range_end: datetime,
    ) -> tuple[PeriodPnl, ...]:
        return tuple(
            pnl
            for pnl in self._by_pnl_id.values()
            if pnl.machine_id == machine_id
            and pnl.opened_at < range_end
            and pnl.closed_at > range_start
        )

    def list_for_machine(self, machine_id: MachineId) -> tuple[PeriodPnl, ...]:
        return tuple(pnl for pnl in self._by_pnl_id.values() if pnl.machine_id == machine_id)
