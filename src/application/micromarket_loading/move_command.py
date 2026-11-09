from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

MoveCommandKind = Literal["create", "delete", "stale_check"]
MoveCommandStatus = Literal["pending", "succeeded", "failed"]


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingMoveCommand:
    command_id: str
    kind: MoveCommandKind
    status: MoveCommandStatus
    order_id: str | None = None
    machine_code: str | None = None
    positions: tuple[tuple[str, Decimal], ...] = ()
    move_id: str | None = None
    stale: bool | None = None
    error: str | None = None


@runtime_checkable
class MicromarketLoadingMoveCommandStore(Protocol):
    @beartype
    def create_pending(self, command: MicromarketLoadingMoveCommand) -> None: ...

    @beartype
    def get(self, command_id: str) -> MicromarketLoadingMoveCommand | None: ...

    @beartype
    def mark_succeeded(
        self,
        *,
        command_id: str,
        move_id: str | None = None,
        stale: bool | None = None,
    ) -> bool: ...

    @beartype
    def mark_failed(self, *, command_id: str, error: str) -> bool: ...
