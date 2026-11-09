from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from beartype import beartype

from src.application.service_visits.models import ServiceVisit, VisitKind, VisitStatus
from src.domain.ids import MachineId
from src.domain.models import VendingMachine

_PREFIX_BY_RANK: dict[int, str] = {
    0: "✴️",
    1: "‼️",
    2: "⏺️",
    3: "✅",
    4: "",
}


@beartype
@dataclass(frozen=True, slots=True)
class VisitListRow:
    machine_id: MachineId
    name: str
    sort_rank: int
    prefix: str


@beartype
def _rank_for_machine(visits: list[ServiceVisit], ops_day: date) -> int:
    has_force = False
    has_today = False
    has_overdue = False
    has_buried = False
    has_done_today = False
    for visit in visits:
        if (
            visit.kind is VisitKind.EXTRA_INCIDENT
            and visit.status is VisitStatus.OPEN
            and visit.closable
        ):
            has_force = True
            continue
        if visit.kind is VisitKind.SCHEDULED and visit.status is VisitStatus.OPEN:
            if visit.priority_boost:
                has_force = True
                continue
            if visit.closable:
                if visit.due_date == ops_day:
                    has_today = True
                elif visit.due_date < ops_day:
                    has_overdue = True
            else:
                has_buried = True
            continue
        if visit.status is VisitStatus.COMPLETED and visit.due_date == ops_day:
            has_done_today = True
    if has_force:
        return 0
    if has_today:
        return 2
    if has_overdue or has_buried:
        return 1
    if has_done_today:
        return 3
    return 4


@beartype
def project_visit_list(
    machines: tuple[VendingMachine, ...],
    visits: tuple[ServiceVisit, ...],
    *,
    ops_day: date,
) -> list[VisitListRow]:
    """Вернуть строки, отсортированные по sort_rank затем name."""
    visits_by_machine: dict[MachineId, list[ServiceVisit]] = defaultdict(list)
    for visit in visits:
        visits_by_machine[visit.machine_id].append(visit)

    rows: list[VisitListRow] = []
    for machine in machines:
        machine_visits = visits_by_machine[machine.id]
        rank = _rank_for_machine(machine_visits, ops_day) if machine_visits else 4
        rows.append(
            VisitListRow(
                machine_id=machine.id,
                name=machine.name,
                sort_rank=rank,
                prefix=_PREFIX_BY_RANK[rank],
            )
        )
    rows.sort(key=lambda row: (row.sort_rank, row.name))
    return rows
