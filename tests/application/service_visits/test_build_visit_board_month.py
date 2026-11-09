from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    CloseType,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.ports import (
    LocationDisplaySnapshot,
    PlacementAtSnapshot,
    RosterEntrySnapshot,
)
from src.application.service_visits.visit_board import (
    BuildVisitBoardMonth,
    VisitBoardCell,
    VisitBoardIconKind,
    VisitBoardRow,
)
from src.domain.ids import MachineId, TechnicianId

_TZ = ZoneInfo("Europe/Moscow")
_DAY_END_HOUR = 6
_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=_TZ)
_TECH = TechnicianId("001")
_OTHER = TechnicianId("002")
_M1 = MachineId("101")
_M2 = MachineId("102")
_LOC1 = "1"
_LOC2 = "2"
_MONTH_START = datetime(2026, 7, 1, tzinfo=UTC)
_RELOCATED_AT = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeRoster:
    entries: tuple[RosterEntrySnapshot, ...]

    def list_entries(self) -> tuple[RosterEntrySnapshot, ...]:
        return self.entries


@dataclass(frozen=True, slots=True)
class _FakePlacement:
    by_machine: dict[MachineId, tuple[PlacementAtSnapshot, ...]]

    def placements_for_machine(
        self,
        machine_id: MachineId,
    ) -> tuple[PlacementAtSnapshot, ...]:
        return self.by_machine.get(machine_id, ())


@dataclass(frozen=True, slots=True)
class _FakeLocations:
    by_id: dict[str, LocationDisplaySnapshot]

    def display_for(self, location_id: str) -> LocationDisplaySnapshot | None:
        return self.by_id.get(location_id)


@dataclass(frozen=True, slots=True)
class _FakeTech:
    names: dict[TechnicianId, str]

    def display_name(self, technician_id: TechnicianId) -> str | None:
        return self.names.get(technician_id)


def _RosterEntry(
    machine_id: MachineId,
    technician_id: TechnicianId | None,
    weekdays: frozenset[int],
) -> RosterEntrySnapshot:
    return RosterEntrySnapshot(
        machine_id=machine_id,
        technician_id=technician_id,
        service_weekdays=weekdays,
    )


def _placement(
    machine_id: MachineId,
    location_id: str,
    *,
    valid_from: datetime = _MONTH_START,
    valid_to: datetime | None = None,
) -> PlacementAtSnapshot:
    return PlacementAtSnapshot(
        machine_id=machine_id,
        location_id=location_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _scheduled_open(machine_id: MachineId, due: date) -> ServiceVisit:
    return ServiceVisit(
        visit_id=f"scheduled:{machine_id.value}:{due.isoformat()}",
        machine_id=machine_id,
        kind=VisitKind.SCHEDULED,
        due_date=due,
        status=VisitStatus.OPEN,
        closable=True,
        priority_boost=False,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _completed(
    machine_id: MachineId,
    day: date,
    close_type: CloseType,
    *,
    technician_id: TechnicianId = _TECH,
    visit_id: str | None = None,
) -> ServiceVisit:
    completed_at = datetime.combine(day, time(12, 0), tzinfo=_TZ)
    kind = VisitKind.SCHEDULED if close_type is CloseType.SCHEDULED else VisitKind.EXTRA_INCIDENT
    return ServiceVisit(
        visit_id=visit_id or f"done:{machine_id.value}:{day.isoformat()}",
        machine_id=machine_id,
        kind=kind,
        due_date=day,
        status=VisitStatus.COMPLETED,
        closable=False,
        priority_boost=False,
        incident_source=None,
        close_type=close_type,
        completed_at=completed_at,
        completed_by_technician_id=technician_id,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=completed_at,
    )


def _build_uc(
    *,
    visits: tuple[ServiceVisit, ...] = (),
    entries: tuple[RosterEntrySnapshot, ...] = (),
    placements: dict[MachineId, tuple[PlacementAtSnapshot, ...]] | None = None,
    locations: dict[str, LocationDisplaySnapshot] | None = None,
    names: dict[TechnicianId, str] | None = None,
) -> BuildVisitBoardMonth:
    store = InMemoryServiceVisitStore()
    for visit in visits:
        store.upsert(visit)
    return BuildVisitBoardMonth(
        visit_store=store,
        roster=_FakeRoster(entries),
        placements=_FakePlacement({} if placements is None else placements),
        locations=_FakeLocations({} if locations is None else locations),
        technicians=_FakeTech({_TECH: "Иван", _OTHER: "Пётр"} if names is None else names),
        timezone=_TZ,
        day_end_hour=_DAY_END_HOUR,
    )


def _cell_for(row: VisitBoardRow, day: date) -> VisitBoardCell:
    for cell in row.cells:
        if cell.day == day:
            return cell
    raise AssertionError(f"cell for {day.isoformat()} is missing")


def test_month_grid_columns_and_today() -> None:
    use_case = _build_uc()

    view = use_case.execute(year=2026, month=8, now=_NOW)

    assert view.year == 2026
    assert view.month == 8
    assert len(view.days) == 31
    assert view.days[0] == date(2026, 8, 1)
    assert view.days[-1] == date(2026, 8, 31)
    assert view.today == date(2026, 8, 20)
    assert view.technicians == ()


def test_roster_section_above_visited_only() -> None:
    use_case = _build_uc(
        visits=(_completed(_M2, date(2026, 8, 11), CloseType.SPONTANEOUS),),
        entries=(
            _RosterEntry(_M1, _TECH, frozenset({1, 3})),
            _RosterEntry(_M2, _OTHER, frozenset({1})),
        ),
        placements={
            _M1: (_placement(_M1, _LOC1),),
            _M2: (_placement(_M2, _LOC2),),
        },
        locations={
            _LOC1: LocationDisplaySnapshot(
                location_id=_LOC1,
                display_name="БЦ Север",
                address="ул. Ленина, 1",
            ),
            _LOC2: LocationDisplaySnapshot(
                location_id=_LOC2,
                display_name="ТЦ Юг",
                address="пр. Мира, 5",
            ),
        },
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    first = view.technicians[0]
    assert first.technician_id == _TECH
    assert first.display_name == "Иван"
    assert [row.location_id for row in first.roster_rows] == [_LOC1]
    assert [row.location_id for row in first.visited_rows] == [_LOC2]
    assert first.roster_rows[0].title == "БЦ Север"
    assert view.technicians[1].technician_id == _OTHER
    assert view.technicians[1].visited_rows == ()


def test_bg_past_needs_scheduled_slot() -> None:
    use_case = _build_uc(
        visits=(_scheduled_open(_M1, date(2026, 8, 4)),),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1, 3})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 4)).background_planned is True
    assert _cell_for(row, date(2026, 8, 11)).background_planned is False


def test_bg_future_from_weekdays() -> None:
    use_case = _build_uc(
        entries=(_RosterEntry(_M1, _TECH, frozenset({1, 3})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 25)).background_planned is True
    assert _cell_for(row, date(2026, 8, 27)).background_planned is True
    assert _cell_for(row, date(2026, 8, 26)).background_planned is False


def test_roster_weekday_change_does_not_paint_past() -> None:
    use_case = _build_uc(
        visits=(_scheduled_open(_M1, date(2026, 8, 4)),),
        entries=(_RosterEntry(_M1, _TECH, frozenset({0})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 3)).background_planned is False
    assert _cell_for(row, date(2026, 8, 10)).background_planned is False
    assert _cell_for(row, date(2026, 8, 17)).background_planned is False
    assert _cell_for(row, date(2026, 8, 4)).background_planned is True
    assert _cell_for(row, date(2026, 8, 24)).background_planned is True


def test_icons_completed_only() -> None:
    use_case = _build_uc(
        visits=(
            _completed(_M1, date(2026, 8, 4), CloseType.SCHEDULED),
            _scheduled_open(_M1, date(2026, 8, 11)),
        ),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 4)).icons == (VisitBoardIconKind.SCHEDULED,)
    assert _cell_for(row, date(2026, 8, 11)).icons == ()


def test_unscheduled_roster_maps_to_spontaneous() -> None:
    use_case = _build_uc(
        visits=(_completed(_M1, date(2026, 8, 4), CloseType.UNSCHEDULED_ROSTER),),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 4)).icons == (VisitBoardIconKind.SPONTANEOUS,)


def test_icon_stack_order() -> None:
    day = date(2026, 8, 4)
    use_case = _build_uc(
        visits=(
            _completed(_M1, day, CloseType.SPONTANEOUS, visit_id="v-spontaneous"),
            _completed(_M1, day, CloseType.EXTRA_INCIDENT, visit_id="v-extra"),
            _completed(_M1, day, CloseType.SCHEDULED, visit_id="v-scheduled"),
        ),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, day).icons == (
        VisitBoardIconKind.SCHEDULED,
        VisitBoardIconKind.EXTRA_INCIDENT,
        VisitBoardIconKind.SPONTANEOUS,
    )


def test_missing_placement_fallback_row() -> None:
    use_case = _build_uc(
        visits=(
            _scheduled_open(_M1, date(2026, 8, 4)),
            _completed(_M1, date(2026, 8, 4), CloseType.SCHEDULED),
        ),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1})),),
        placements={},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert row.location_id is None
    assert row.placement_missing is True
    assert "101" in row.title
    assert _cell_for(row, date(2026, 8, 4)).background_planned is True
    assert _cell_for(row, date(2026, 8, 4)).icons == (VisitBoardIconKind.SCHEDULED,)


def test_technician_without_rows_omitted() -> None:
    use_case = _build_uc(
        entries=(_RosterEntry(_M1, None, frozenset({1, 3})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    assert view.technicians == ()


def test_relocation_mid_month_two_rows() -> None:
    use_case = _build_uc(
        visits=(
            _completed(_M1, date(2026, 8, 4), CloseType.SCHEDULED, visit_id="v-old"),
            _completed(_M1, date(2026, 8, 18), CloseType.SCHEDULED, visit_id="v-new"),
        ),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1, 3})),),
        placements={
            _M1: (
                _placement(_M1, _LOC1, valid_to=_RELOCATED_AT),
                _placement(_M1, _LOC2, valid_from=_RELOCATED_AT),
            ),
        },
        locations={
            _LOC1: LocationDisplaySnapshot(
                location_id=_LOC1,
                display_name="БЦ Север",
                address="ул. Ленина, 1",
            ),
            _LOC2: LocationDisplaySnapshot(
                location_id=_LOC2,
                display_name="ТЦ Юг",
                address="пр. Мира, 5",
            ),
        },
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    block = view.technicians[0]
    assert [row.location_id for row in block.roster_rows] == [_LOC2]
    assert [row.location_id for row in block.visited_rows] == [_LOC1]
    old_row = block.visited_rows[0]
    new_row = block.roster_rows[0]
    assert _cell_for(old_row, date(2026, 8, 4)).icons == (VisitBoardIconKind.SCHEDULED,)
    assert _cell_for(old_row, date(2026, 8, 18)).icons == ()
    assert _cell_for(new_row, date(2026, 8, 18)).icons == (VisitBoardIconKind.SCHEDULED,)
    assert _cell_for(new_row, date(2026, 8, 4)).icons == ()


def test_ad_hoc_spontaneous_does_not_paint_past_bg() -> None:
    # Production CloseServiceVisit._upsert_ad_hoc: kind=SCHEDULED, close_type=SPONTANEOUS
    visit = ServiceVisit(
        visit_id=f"ad_hoc:{_M1.value}:2026-08-04:evt-1",
        machine_id=_M1,
        kind=VisitKind.SCHEDULED,
        due_date=date(2026, 8, 4),
        status=VisitStatus.COMPLETED,
        closable=False,
        priority_boost=False,
        incident_source=None,
        close_type=CloseType.SPONTANEOUS,
        completed_at=datetime(2026, 8, 4, 12, 0, tzinfo=_TZ),
        completed_by_technician_id=_TECH,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    use_case = _build_uc(
        visits=(visit,),
        entries=(_RosterEntry(_M1, _TECH, frozenset({1})),),
        placements={_M1: (_placement(_M1, _LOC1),)},
    )

    view = use_case.execute(year=2026, month=8, now=_NOW)

    row = view.technicians[0].roster_rows[0]
    assert _cell_for(row, date(2026, 8, 4)).background_planned is False
    assert _cell_for(row, date(2026, 8, 4)).icons == (VisitBoardIconKind.SPONTANEOUS,)
