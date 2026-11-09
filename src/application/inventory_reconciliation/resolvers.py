from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.inventory_reconciliation.ports import VendingMachineCodeResolver
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class IdentityVendingMachineCodeResolver(VendingMachineCodeResolver):
    @beartype
    def resolve(self, code: str) -> MachineId | None:
        stripped = code.strip()
        return MachineId(stripped) if stripped else None

    @beartype
    def list_codes(self) -> tuple[str, ...]:
        return ()


@beartype
@dataclass(frozen=True, slots=True)
class MappingVendingMachineCodeResolver(VendingMachineCodeResolver):
    mapping: dict[str, MachineId]

    @beartype
    def resolve(self, code: str) -> MachineId | None:
        return self.mapping.get(code)

    @beartype
    def list_codes(self) -> tuple[str, ...]:
        return tuple(self.mapping)
