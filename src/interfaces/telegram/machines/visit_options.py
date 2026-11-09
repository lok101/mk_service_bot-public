from __future__ import annotations

from datetime import date

from beartype import beartype

from src.application.service_visits import ServiceVisit, project_visit_list
from src.domain.ids import MachineId
from src.domain.models import VendingMachine
from src.interfaces.telegram.contracts import TelegramMachineOption
from src.interfaces.telegram.machines.labels import format_machine_list_label


@beartype
def machine_options_from_visits(
    machines: tuple[VendingMachine, ...],
    visits: tuple[ServiceVisit, ...],
    *,
    ops_day: date,
    revision_due_machine_ids: frozenset[MachineId] = frozenset(),
) -> list[TelegramMachineOption]:
    rows = project_visit_list(machines, visits, ops_day=ops_day)
    return [
        TelegramMachineOption(
            id=row.machine_id,
            name=_list_label(
                prefix=row.prefix,
                name=row.name,
                revision_due=row.machine_id in revision_due_machine_ids,
            ),
        )
        for row in rows
    ]


@beartype
def _list_label(*, prefix: str, name: str, revision_due: bool) -> str:
    formatted = format_machine_list_label(name)
    if revision_due:
        return f"{prefix} ⚖️ {formatted}"
    return f"{prefix} {formatted}"
