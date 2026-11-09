from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.list_projection import project_visit_list
from src.application.service_visits.models import (
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId
from src.domain.models import VendingMachine

_OPS = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _vm(code: str, name: str) -> VendingMachine:
    return VendingMachine(id=MachineId(code), name=name)


def _open_scheduled(
    code: str,
    *,
    closable: bool,
    boost: bool,
    due: date | None = None,
) -> ServiceVisit:
    machine_id = MachineId(code)
    due_date = _OPS if due is None else due
    return ServiceVisit(
        visit_id=scheduled_visit_id(machine_id, due_date),
        machine_id=machine_id,
        kind=VisitKind.SCHEDULED,
        due_date=due_date,
        status=VisitStatus.OPEN,
        closable=closable,
        priority_boost=boost,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_list_sorts_boost_before_scheduled_before_done() -> None:
    rows = project_visit_list(
        (
            _vm("3", "Готово"),
            _vm("2", "План"),
            _vm("1", "Буст"),
        ),
        (
            _open_scheduled("1", closable=True, boost=True),
            _open_scheduled("2", closable=True, boost=False),
            ServiceVisit(
                visit_id="ad_hoc:3:2026-08-12:e1",
                machine_id=MachineId("3"),
                kind=VisitKind.SCHEDULED,
                due_date=_OPS,
                status=VisitStatus.COMPLETED,
                closable=False,
                priority_boost=False,
                incident_source=None,
                close_type=None,
                completed_at=_NOW,
                completed_by_technician_id=None,
                maintenance_event_id=None,
                created_at=_NOW,
                updated_at=_NOW,
            ),
        ),
        ops_day=_OPS,
    )
    assert [row.machine_id.value for row in rows] == ["1", "2", "3"]


def test_list_prefixes_match_visit_ranks() -> None:
    extra = ServiceVisit(
        visit_id="incident:offline:e",
        machine_id=MachineId("9"),
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=_OPS,
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
    buried = _open_scheduled("8", closable=False, boost=False)
    buried = ServiceVisit(
        visit_id=buried.visit_id,
        machine_id=buried.machine_id,
        kind=buried.kind,
        due_date=date(2026, 8, 11),
        status=VisitStatus.OPEN,
        closable=False,
        priority_boost=False,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    rows = project_visit_list(
        (_vm("9", "Extra"), _vm("8", "Пропуск"), _vm("7", "Обычный"), _vm("0", "Прочее")),
        (extra, buried, _open_scheduled("7", closable=True, boost=False)),
        ops_day=_OPS,
    )
    by_id = {row.machine_id.value: row.prefix for row in rows}
    assert by_id["9"] == "✴️"
    assert by_id["8"] == "‼️"
    assert by_id["7"] == "⏺️"
    assert by_id["0"] == ""


def test_overdue_closable_leftover_prefix_is_double_exclamation() -> None:
    ops = date(2026, 8, 13)  # чт
    leftover_due = date(2026, 8, 10)  # пн
    rows = project_visit_list(
        (_vm("166", "Прод 166"),),
        (_open_scheduled("166", closable=True, boost=False, due=leftover_due),),
        ops_day=ops,
    )
    assert rows[0].prefix == "‼️"
    assert rows[0].sort_rank == 1


def test_today_closable_scheduled_prefix_is_record() -> None:
    rows = project_visit_list(
        (_vm("7", "Обычный"),),
        (_open_scheduled("7", closable=True, boost=False),),
        ops_day=_OPS,
    )
    assert rows[0].prefix == "⏺️"
    assert rows[0].sort_rank == 2


def test_buried_plus_today_closable_prefers_today_prefix() -> None:
    ops = date(2026, 8, 14)  # пт
    buried = _open_scheduled("1", closable=False, boost=False, due=date(2026, 8, 10))
    today = _open_scheduled("1", closable=True, boost=False, due=ops)
    rows = project_visit_list(
        (_vm("1", "Машина"),),
        (buried, today),
        ops_day=ops,
    )
    assert rows[0].prefix == "⏺️"
    assert rows[0].sort_rank == 2


def test_thursday_only_monday_leftover_is_overdue_prefix() -> None:
    """пн+пт график: в чт слота нет — leftover пн → ‼️."""
    ops = date(2026, 8, 13)
    rows = project_visit_list(
        (_vm("106", "106"),),
        (_open_scheduled("106", closable=True, boost=False, due=date(2026, 8, 10)),),
        ops_day=ops,
    )
    assert rows[0].prefix == "‼️"


def test_extra_closable_beats_overdue_leftover() -> None:
    ops = date(2026, 8, 13)
    leftover = _open_scheduled("9", closable=True, boost=False, due=date(2026, 8, 10))
    extra = ServiceVisit(
        visit_id="incident:offline:9",
        machine_id=MachineId("9"),
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=ops,
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
    rows = project_visit_list(
        (_vm("9", "Extra"),),
        (leftover, extra),
        ops_day=ops,
    )
    assert rows[0].prefix == "✴️"
    assert rows[0].sort_rank == 0


def test_only_buried_open_scheduled_is_double_exclamation() -> None:
    buried = _open_scheduled("8", closable=False, boost=False, due=date(2026, 8, 11))
    rows = project_visit_list(
        (_vm("8", "Пропуск"),),
        (buried,),
        ops_day=_OPS,
    )
    assert rows[0].prefix == "‼️"


def test_future_due_closable_does_not_get_plan_prefix() -> None:
    future = _open_scheduled("5", closable=True, boost=False, due=date(2026, 8, 20))
    rows = project_visit_list(
        (_vm("5", "Будущее"),),
        (future,),
        ops_day=_OPS,
    )
    assert rows[0].prefix == ""
    assert rows[0].sort_rank == 4


def test_cleared_closable_extra_does_not_force_prefix() -> None:
    """edge: CLEARED extra with closable=true must not yield ✴️; today plan → ⏺️."""
    cleared_extra = ServiceVisit(
        visit_id="incident:no_sales:4",
        machine_id=MachineId("4"),
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=_OPS,
        status=VisitStatus.CLEARED,
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
    today = _open_scheduled("4", closable=True, boost=False)
    rows = project_visit_list(
        (_vm("4", "После глушения"),),
        (cleared_extra, today),
        ops_day=_OPS,
    )
    assert rows[0].prefix == "⏺️"
    assert rows[0].sort_rank == 2
