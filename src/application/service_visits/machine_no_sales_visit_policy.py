from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId


@runtime_checkable
class MachineNoSalesVisitPolicy(Protocol):
    def allows_create_visit_on_no_sales(self, machine_id: MachineId) -> bool: ...


@beartype
class AlwaysAllowNoSalesVisitPolicy:
    def allows_create_visit_on_no_sales(self, machine_id: MachineId) -> bool:
        del machine_id
        return True
