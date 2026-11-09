from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from beartype import beartype

from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryMonthPnlSnapshotStore:
    _by_key: dict[tuple[str, date], MonthPnlSnapshot] = field(default_factory=dict)

    def upsert(self, snapshot: MonthPnlSnapshot) -> None:
        self._by_key[(snapshot.machine_id.value, snapshot.period_start)] = snapshot

    def get(self, machine_id: MachineId, period_start: date) -> MonthPnlSnapshot | None:
        return self._by_key.get((machine_id.value, period_start))

    def list_for_period_starts(
        self,
        period_starts: Sequence[date],
    ) -> tuple[MonthPnlSnapshot, ...]:
        wanted = set(period_starts)
        if not wanted:
            return ()
        return tuple(
            snapshot for snapshot in self._by_key.values() if snapshot.period_start in wanted
        )
