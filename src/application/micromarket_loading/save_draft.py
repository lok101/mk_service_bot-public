from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle


@runtime_checkable
class MicromarketLoadingCycleStore(Protocol):
    def load(self, machine_code: str) -> MicromarketLoadingCycle | None: ...

    def save(self, cycle: MicromarketLoadingCycle) -> None: ...


@beartype
@dataclass(slots=True)
class SaveMicromarketLoadingDraft:
    cycle_store: MicromarketLoadingCycleStore

    @beartype
    def execute(
        self,
        *,
        machine_code: str,
        lines: tuple[DraftLine, ...],
    ) -> None:
        cycle = self.cycle_store.load(machine_code)
        if cycle is None:
            cycle = MicromarketLoadingCycle(machine_code=machine_code)
        cycle.save_draft(lines)
        self.cycle_store.save(cycle)
