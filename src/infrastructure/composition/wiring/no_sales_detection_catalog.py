from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.sales_monitoring.run_sales_report import CatalogMachine
from src.domain.ids import MachineId

_ADDED_KINDS = frozenset({"snack", "micro_market"})


@beartype
@dataclass(frozen=True, slots=True)
class NoSalesParkMachine:
    machine_id: MachineId
    kind: str
    status: str
    name: str


@beartype
def merge_no_sales_detection_catalog(
    coffee: Sequence[CatalogMachine],
    park: Sequence[NoSalesParkMachine],
) -> tuple[CatalogMachine, ...]:
    seen = {entry.machine_id for entry in coffee}
    added: list[CatalogMachine] = []
    for machine in park:
        if machine.kind not in _ADDED_KINDS or machine.status != "active_on_site":
            continue
        if machine.machine_id in seen:
            continue
        seen.add(machine.machine_id)
        added.append(
            CatalogMachine(
                machine_id=machine.machine_id,
                name=machine.name,
                assigned_technician_id=None,
                assigned_technician_display=None,
            )
        )
    return tuple(coffee) + tuple(added)


@beartype
def status_board_catalog(coffee: Sequence[CatalogMachine]) -> Sequence[CatalogMachine]:
    return coffee
