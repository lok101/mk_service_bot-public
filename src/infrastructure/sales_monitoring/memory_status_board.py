from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.sales_monitoring.status_board_pointer import StatusBoardPointer


@beartype
@dataclass
class InMemoryStatusBoardPointerStore:
    _pointer: StatusBoardPointer | None = None

    @beartype
    def load(self) -> StatusBoardPointer | None:
        return self._pointer

    @beartype
    def save(self, pointer: StatusBoardPointer) -> None:
        self._pointer = pointer
