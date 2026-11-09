from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.service_visits.models import CloseType, ServiceVisit, VisitStatus
from src.application.service_visits.placement_at import resolve_placement_at
from src.application.service_visits.ports import (
    LocationDisplayLookup,
    PlacementAtLookup,
    PlacementAtSnapshot,
    RosterEntriesLookup,
    ServiceVisitStore,
    TechnicianDisplayLookup,
)
from src.domain.calendar import operational_day
from src.domain.ids import MachineId, TechnicianId


class VisitBoardIconKind(StrEnum):
    SCHEDULED = "scheduled"
    EXTRA_INCIDENT = "extra_incident"
    SPONTANEOUS = "spontaneous"


@beartype
@dataclass(frozen=True, slots=True)
class VisitBoardCell:
    day: date
    background_planned: bool
    icons: tuple[VisitBoardIconKind, ...]


@beartype
@dataclass(frozen=True, slots=True)
class VisitBoardRow:
    location_id: str | None
    title: str
    machine_ids: tuple[MachineId, ...]
    cells: tuple[VisitBoardCell, ...]
    placement_missing: bool


@beartype
@dataclass(frozen=True, slots=True)
class VisitBoardTechnicianBlock:
    technician_id: TechnicianId
    display_name: str
    roster_rows: tuple[VisitBoardRow, ...]
    visited_rows: tuple[VisitBoardRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class VisitBoardView:
    year: int
    month: int
    days: tuple[date, ...]
    today: date
    technicians: tuple[VisitBoardTechnicianBlock, ...]


_ICON_BY_CLOSE_TYPE: dict[CloseType, VisitBoardIconKind] = {
    CloseType.SCHEDULED: VisitBoardIconKind.SCHEDULED,
    CloseType.EXTRA_INCIDENT: VisitBoardIconKind.EXTRA_INCIDENT,
    CloseType.SPONTANEOUS: VisitBoardIconKind.SPONTANEOUS,
    CloseType.UNSCHEDULED_ROSTER: VisitBoardIconKind.SPONTANEOUS,
}
_ICON_ORDER: tuple[VisitBoardIconKind, ...] = (
    VisitBoardIconKind.SCHEDULED,
    VisitBoardIconKind.EXTRA_INCIDENT,
    VisitBoardIconKind.SPONTANEOUS,
)
_DAY_REFERENCE_HOUR = 12


@beartype
def _month_days(year: int, month: int) -> tuple[date, ...]:
    first = date(year, month, 1)
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return tuple(first + timedelta(days=offset) for offset in range((following - first).days))


@beartype
def _day_instant(day: date, timezone: ZoneInfo) -> datetime:
    return datetime.combine(day, time(_DAY_REFERENCE_HOUR, 0), tzinfo=timezone)


@beartype
def _icons_for_day(
    *,
    completed: tuple[tuple[date, ServiceVisit], ...],
    day: date,
    machine_ids: tuple[MachineId, ...],
) -> tuple[VisitBoardIconKind, ...]:
    found: list[VisitBoardIconKind] = []
    for visit_day, visit in completed:
        if visit_day != day or visit.machine_id not in machine_ids:
            continue
        if visit.close_type is None:
            continue
        found.append(_ICON_BY_CLOSE_TYPE[visit.close_type])
    return tuple(sorted(found, key=_ICON_ORDER.index))


@beartype
@dataclass(frozen=True, slots=True)
class BuildVisitBoardMonth:
    visit_store: ServiceVisitStore
    roster: RosterEntriesLookup
    placements: PlacementAtLookup
    locations: LocationDisplayLookup
    technicians: TechnicianDisplayLookup
    timezone: ZoneInfo
    day_end_hour: int

    @beartype
    def execute(self, *, year: int, month: int, now: datetime) -> VisitBoardView:
        days = _month_days(year, month)
        today = operational_day(now, self.timezone, self.day_end_hour)
        visits = tuple(self.visit_store.list_for_due_date_range(start=days[0], end=days[-1]))

        entries = self.roster.list_entries()
        weekdays_by_machine = {entry.machine_id: entry.service_weekdays for entry in entries}
        roster_machines: dict[TechnicianId, list[MachineId]] = defaultdict(list)
        for entry in entries:
            if entry.technician_id is not None:
                roster_machines[entry.technician_id].append(entry.machine_id)

        scheduled_days: dict[MachineId, set[date]] = defaultdict(set)
        completed_by_technician: dict[TechnicianId, list[tuple[date, ServiceVisit]]] = defaultdict(
            list
        )
        for visit in visits:
            if visit.visit_id.startswith("scheduled:"):
                scheduled_days[visit.machine_id].add(visit.due_date)
            if visit.status is not VisitStatus.COMPLETED:
                continue
            technician_id = visit.completed_by_technician_id
            if technician_id is None:
                continue
            completed_by_technician[technician_id].append((self._visit_day(visit), visit))

        blocks: list[VisitBoardTechnicianBlock] = []
        technician_ids = set(roster_machines) | set(completed_by_technician)
        for technician_id in sorted(technician_ids, key=lambda item: item.value):
            block = self._build_block(
                technician_id=technician_id,
                roster_machine_ids=tuple(roster_machines.get(technician_id, ())),
                completed=tuple(completed_by_technician.get(technician_id, ())),
                days=days,
                today=today,
                weekdays_by_machine=weekdays_by_machine,
                scheduled_days=scheduled_days,
                now=now,
            )
            if block is not None:
                blocks.append(block)

        return VisitBoardView(
            year=year,
            month=month,
            days=days,
            today=today,
            technicians=tuple(blocks),
        )

    @beartype
    def _visit_day(self, visit: ServiceVisit) -> date:
        if visit.completed_at is None:
            return visit.due_date
        return operational_day(visit.completed_at, self.timezone, self.day_end_hour)

    @beartype
    def _placements_for(self, machine_id: MachineId) -> tuple[PlacementAtSnapshot, ...]:
        return self.placements.placements_for_machine(machine_id)

    @beartype
    def _build_block(
        self,
        *,
        technician_id: TechnicianId,
        roster_machine_ids: tuple[MachineId, ...],
        completed: tuple[tuple[date, ServiceVisit], ...],
        days: tuple[date, ...],
        today: date,
        weekdays_by_machine: dict[MachineId, frozenset[int]],
        scheduled_days: dict[MachineId, set[date]],
        now: datetime,
    ) -> VisitBoardTechnicianBlock | None:
        roster_groups: dict[str, list[MachineId]] = {}
        roster_fallback: list[MachineId] = []
        for machine_id in roster_machine_ids:
            placement = resolve_placement_at(self._placements_for(machine_id), now)
            if placement is None:
                roster_fallback.append(machine_id)
                continue
            roster_groups.setdefault(placement.location_id, []).append(machine_id)

        visited_groups: dict[str, list[MachineId]] = {}
        visited_fallback: list[MachineId] = []
        for _visit_day, visit in completed:
            at = visit.completed_at if visit.completed_at is not None else now
            placement = resolve_placement_at(self._placements_for(visit.machine_id), at)
            if placement is None:
                if visit.machine_id not in roster_fallback and (
                    visit.machine_id not in visited_fallback
                ):
                    visited_fallback.append(visit.machine_id)
                continue
            if placement.location_id in roster_groups:
                continue
            machines = visited_groups.setdefault(placement.location_id, [])
            if visit.machine_id not in machines:
                machines.append(visit.machine_id)

        roster_rows = tuple(
            self._build_row(
                location_id=location_id,
                machine_ids=tuple(machine_ids),
                days=days,
                today=today,
                completed=completed,
                weekdays_by_machine=weekdays_by_machine,
                scheduled_days=scheduled_days,
                future_from_weekdays=True,
            )
            for location_id, machine_ids in sorted(roster_groups.items())
        ) + tuple(
            self._build_fallback_row(
                machine_id=machine_id,
                days=days,
                today=today,
                completed=completed,
                scheduled_days=scheduled_days,
            )
            for machine_id in roster_fallback
        )
        visited_rows = tuple(
            self._build_row(
                location_id=location_id,
                machine_ids=tuple(machine_ids),
                days=days,
                today=today,
                completed=completed,
                weekdays_by_machine=weekdays_by_machine,
                scheduled_days=scheduled_days,
                future_from_weekdays=False,
            )
            for location_id, machine_ids in sorted(visited_groups.items())
        ) + tuple(
            self._build_fallback_row(
                machine_id=machine_id,
                days=days,
                today=today,
                completed=completed,
                scheduled_days=scheduled_days,
            )
            for machine_id in visited_fallback
        )
        if not roster_rows and not visited_rows:
            return None
        display_name = self.technicians.display_name(technician_id) or technician_id.value
        return VisitBoardTechnicianBlock(
            technician_id=technician_id,
            display_name=display_name,
            roster_rows=roster_rows,
            visited_rows=visited_rows,
        )

    @beartype
    def _covers(self, machine_id: MachineId, location_id: str, day: date) -> bool:
        placement = resolve_placement_at(
            self._placements_for(machine_id),
            _day_instant(day, self.timezone),
        )
        return placement is not None and placement.location_id == location_id

    @beartype
    def _build_row(
        self,
        *,
        location_id: str,
        machine_ids: tuple[MachineId, ...],
        days: tuple[date, ...],
        today: date,
        completed: tuple[tuple[date, ServiceVisit], ...],
        weekdays_by_machine: dict[MachineId, frozenset[int]],
        scheduled_days: dict[MachineId, set[date]],
        future_from_weekdays: bool,
    ) -> VisitBoardRow:
        display = self.locations.display_for(location_id)
        title = location_id
        if display is not None:
            title = display.display_name or display.address or location_id
        cells: list[VisitBoardCell] = []
        for day in days:
            covering = tuple(
                machine_id
                for machine_id in machine_ids
                if self._covers(machine_id, location_id, day)
            )
            if not covering:
                planned = False
            elif day <= today:
                planned = any(day in scheduled_days.get(item, set()) for item in covering)
            elif not future_from_weekdays:
                planned = False
            else:
                planned = any(
                    day.weekday() in weekdays_by_machine.get(item, frozenset()) for item in covering
                )
            cells.append(
                VisitBoardCell(
                    day=day,
                    background_planned=planned,
                    icons=_icons_for_day(completed=completed, day=day, machine_ids=covering),
                )
            )
        return VisitBoardRow(
            location_id=location_id,
            title=title,
            machine_ids=machine_ids,
            cells=tuple(cells),
            placement_missing=False,
        )

    @beartype
    def _build_fallback_row(
        self,
        *,
        machine_id: MachineId,
        days: tuple[date, ...],
        today: date,
        completed: tuple[tuple[date, ServiceVisit], ...],
        scheduled_days: dict[MachineId, set[date]],
    ) -> VisitBoardRow:
        cells = tuple(
            VisitBoardCell(
                day=day,
                background_planned=day <= today and day in scheduled_days.get(machine_id, set()),
                icons=_icons_for_day(completed=completed, day=day, machine_ids=(machine_id,)),
            )
            for day in days
        )
        return VisitBoardRow(
            location_id=None,
            title=f"Аппарат {machine_id.value} (точка не определена)",
            machine_ids=(machine_id,),
            cells=cells,
            placement_missing=True,
        )
