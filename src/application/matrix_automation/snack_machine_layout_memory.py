from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.matrix_automation.snack_machine_layout import SnackMachineLayout


@beartype
@dataclass(slots=True)
class InMemorySnackMachineLayoutStore:
    _by_code: dict[str, SnackMachineLayout] = field(default_factory=dict)

    def get(self, machine_code: str) -> SnackMachineLayout | None:
        return self._by_code.get(machine_code)

    def upsert(self, layout: SnackMachineLayout) -> None:
        self._by_code[layout.machine_code] = layout

    def list_all(self) -> tuple[SnackMachineLayout, ...]:
        return tuple(self._by_code.values())

    def count(self) -> int:
        return len(self._by_code)
