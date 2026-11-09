from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, create_autospec
from zoneinfo import ZoneInfo

from src.application.machine_operations.ports import MachineOperationsRepository
from src.application.machine_operations.use_cases import GetServiceCapabilities
from src.application.master_data import MachineKind
from src.application.service_visits.models import ServiceVisit, VisitKind, VisitStatus
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.getters import _coffee_revision_due_machine_ids
from src.interfaces.telegram.machines.visit_options import machine_options_from_visits

_OPS = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _open_visit(machine_id: MachineId, *, boost: bool = False) -> ServiceVisit:
    return ServiceVisit(
        visit_id=scheduled_visit_id(machine_id, _OPS),
        machine_id=machine_id,
        kind=VisitKind.SCHEDULED,
        due_date=_OPS,
        status=VisitStatus.OPEN,
        closable=True,
        priority_boost=boost,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_machine_list_revision_due_mark_coffee_handover() -> None:
    # happy: ⚖️ after visit-prefix for coffee awaiting_handover; sort unchanged
    coffee_handover = MachineId("10")
    coffee_ok = MachineId("20")
    snack = MachineId("30")
    machines = (
        VendingMachine(id=coffee_ok, name="102 - Кафе | адрес"),
        VendingMachine(id=snack, name="301 - Снек | адрес"),
        VendingMachine(id=coffee_handover, name="101 - Школа | адрес"),
    )
    visits = (
        _open_visit(coffee_ok),
        _open_visit(snack, boost=True),
        _open_visit(coffee_handover),
    )
    without_mark = machine_options_from_visits(machines, visits, ops_day=_OPS)
    with_mark = machine_options_from_visits(
        machines,
        visits,
        ops_day=_OPS,
        revision_due_machine_ids=frozenset({coffee_handover}),
    )

    assert [opt.id for opt in with_mark] == [opt.id for opt in without_mark]
    handover_label = next(opt.name for opt in with_mark if opt.id == coffee_handover)
    ok_label = next(opt.name for opt in with_mark if opt.id == coffee_ok)
    snack_label = next(opt.name for opt in with_mark if opt.id == snack)
    assert "⚖️" in handover_label
    prefix, _, rest = handover_label.partition(" ")
    assert prefix in {"⏺️", "✅", "✴️", "‼️"}
    assert rest.startswith("⚖️")
    assert "⚖️" not in ok_label
    assert "⚖️" not in snack_label


def test_coffee_revision_due_ids_uses_aggregate_phase_without_caps() -> None:
    # error/regression: list ⚖️ must not call GetServiceCapabilities (no form token mint)
    coffee_handover = MachineId("10")
    coffee_ok = MachineId("20")
    snack = MachineId("30")
    machines = (
        VendingMachine(id=coffee_ok, name="102 - Кафе | адрес"),
        VendingMachine(id=snack, name="301 - Снек | адрес"),
        VendingMachine(id=coffee_handover, name="101 - Школа | адрес"),
    )
    tech = TechnicianId("001")
    aggregates = {
        coffee_handover: MagicMock(
            responsibility_phase=MagicMock(return_value="awaiting_handover"),
        ),
        coffee_ok: MagicMock(responsibility_phase=MagicMock(return_value="responsible")),
        snack: MagicMock(responsibility_phase=MagicMock(return_value="awaiting_handover")),
    }
    machine_ops = create_autospec(MachineOperationsRepository, instance=True)
    machine_ops.get.side_effect = lambda machine_id: aggregates[machine_id]
    get_caps = create_autospec(GetServiceCapabilities, instance=True)
    kind_lookup = MagicMock()
    kind_lookup.kind_of.side_effect = lambda raw: (
        MachineKind.SNACK if raw == "30" else MachineKind.COFFEE
    )
    deps = MagicMock(spec=MachineListDeps)
    deps.service_display_timezone = ZoneInfo("Europe/Moscow")
    deps.service_day_end_hour = 6
    deps.machine_operations = machine_ops
    deps.get_service_capabilities = get_caps
    deps.machine_kind_lookup = kind_lookup

    due = _coffee_revision_due_machine_ids(
        deps,
        machines=machines,
        technician_id=tech,
    )

    assert due == frozenset({coffee_handover})
    get_caps.execute.assert_not_called()
    aggregates[snack].responsibility_phase.assert_not_called()
    aggregates[coffee_handover].responsibility_phase.assert_called_once_with(tech)
    aggregates[coffee_ok].responsibility_phase.assert_called_once_with(tech)
