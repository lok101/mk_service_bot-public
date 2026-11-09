from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.models import ServiceVisit, VisitKind, VisitStatus
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId
from src.domain.models import VendingMachine
from src.interfaces.telegram.machines.visit_options import machine_options_from_visits

_OPS = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def test_machine_options_prefix_boost_machine() -> None:
    machine_id = MachineId("1")
    visit = ServiceVisit(
        visit_id=scheduled_visit_id(machine_id, _OPS),
        machine_id=machine_id,
        kind=VisitKind.SCHEDULED,
        due_date=_OPS,
        status=VisitStatus.OPEN,
        closable=True,
        priority_boost=True,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    options = machine_options_from_visits(
        machines=(VendingMachine(id=machine_id, name="101 - Школа | адрес"),),
        visits=(visit,),
        ops_day=_OPS,
    )
    assert options[0].name.startswith("✴️")
