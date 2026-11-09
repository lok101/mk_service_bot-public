from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.models import ServiceVisit, VisitKind, VisitStatus
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId
from src.domain.models import VendingMachine
from src.interfaces.telegram.machines.labels import (
    MACHINE_LIST_NAME_WIDTH,
    format_machine_list_label,
)
from src.interfaces.telegram.machines.visit_options import machine_options_from_visits

_OPS = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _open_visit(machine_id: MachineId) -> ServiceVisit:
    return ServiceVisit(
        visit_id=scheduled_visit_id(machine_id, _OPS),
        machine_id=machine_id,
        kind=VisitKind.SCHEDULED,
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


def test_machine_list_label_keeps_ljust_padding_for_telegram_align() -> None:
    # happy: visit_options must not strip trailing spaces from format_machine_list_label
    machine_id = MachineId("1")
    raw_name = "101 - Коворкинг | 8 марта, 12А"
    options = machine_options_from_visits(
        machines=(VendingMachine(id=machine_id, name=raw_name),),
        visits=(_open_visit(machine_id),),
        ops_day=_OPS,
    )

    label = options[0].name
    formatted = format_machine_list_label(raw_name)
    assert formatted.endswith(" ")
    assert len(formatted) == MACHINE_LIST_NAME_WIDTH
    assert label.endswith(" ")
    assert label.endswith(formatted)
    assert not label.endswith(formatted.rstrip())


def test_machine_list_label_keeps_padding_for_long_location_name() -> None:
    # edge: long display name still left-pads to MACHINE_LIST_NAME_WIDTH via trailing spaces
    machine_id = MachineId("2")
    location = "Очень длинное название локации с адресом | ул. Примерная, дом 100 корпус 2"
    raw_name = f"999 - {location}"
    options = machine_options_from_visits(
        machines=(VendingMachine(id=machine_id, name=raw_name),),
        visits=(_open_visit(machine_id),),
        ops_day=_OPS,
    )

    label = options[0].name
    formatted = format_machine_list_label(raw_name)
    assert len(formatted) == MACHINE_LIST_NAME_WIDTH
    assert label.endswith(formatted)
    assert label.rstrip() != label
