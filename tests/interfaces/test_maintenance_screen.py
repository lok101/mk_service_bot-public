from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec
from zoneinfo import ZoneInfo

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.machine_operations.ports import (
    MachineOperationsRepository,
    VendingMachineRepository,
)
from src.application.machine_operations.use_cases import (
    CompleteMaintenance,
    CreateLoadingForm,
    GetServiceCapabilities,
    ListAvailableMachines,
)
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.domain.ids import MachineId
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.maintenance_screen import (
    format_last_loading_line,
    format_last_service_line,
    format_service_datetime,
    last_loading_line_for_machine,
    last_service_line_for_machine,
)

_MSK = ZoneInfo("Europe/Moscow")


def _deps_with_aggregate(aggregate: MagicMock) -> MachineListDeps:
    machine_operations = create_autospec(MachineOperationsRepository, instance=True)
    machine_operations.get.return_value = aggregate
    return MachineListDeps(
        service_display_timezone=_MSK,
        service_day_end_hour=6,
        visit_store=InMemoryServiceVisitStore(),
        telegram_user_resolver=create_autospec(TelegramUserResolver, instance=True),
        vending_machine_repository=create_autospec(VendingMachineRepository, instance=True),
        machine_operations=machine_operations,
        list_available_machines=create_autospec(ListAvailableMachines, instance=True),
        get_service_capabilities=create_autospec(GetServiceCapabilities, instance=True),
        complete_maintenance=create_autospec(CompleteMaintenance, instance=True),
        create_loading_form=create_autospec(CreateLoadingForm, instance=True),
        form_workflow_sessions=create_autospec(FormWorkflowSessionStore, instance=True),
        accept_loading_photos=create_autospec(AcceptLoadingPhotosService, instance=True),
        loading_photos_min_count=1,
        loading_photos_max_count=10,
        maintenance_cooldown_minutes=20,
    )


def test_format_service_datetime_uses_moscow_timezone() -> None:
    value = datetime(2026, 5, 22, 9, 30, tzinfo=UTC)

    assert format_service_datetime(value, _MSK) == "22.05.2026 12:30"


def test_format_last_loading_line_with_datetime() -> None:
    value = datetime(2026, 6, 9, 11, 30, tzinfo=UTC)

    assert format_last_loading_line(value, _MSK) == "📦 Последняя загрузка: 09.06.2026 14:30"


def test_format_last_loading_line_no_data() -> None:
    assert format_last_loading_line(None, _MSK) == "📦 Последняя загрузка: нет данных"


def test_last_loading_line_for_machine_reads_aggregate() -> None:
    submitted_at = datetime(2026, 6, 9, 11, 30, tzinfo=UTC)
    aggregate = MagicMock()
    aggregate.last_loading_submitted_at.return_value = submitted_at
    deps = _deps_with_aggregate(aggregate)

    line = last_loading_line_for_machine(deps, MachineId("vm-1"))

    assert line == "📦 Последняя загрузка: 09.06.2026 14:30"
    deps.machine_operations.get.assert_called_once_with(MachineId("vm-1"))
    aggregate.last_loading_submitted_at.assert_called_once_with()


def test_last_loading_line_for_machine_no_data() -> None:
    aggregate = MagicMock()
    aggregate.last_loading_submitted_at.return_value = None
    deps = _deps_with_aggregate(aggregate)

    line = last_loading_line_for_machine(deps, MachineId("vm-1"))

    assert line == "📦 Последняя загрузка: нет данных"


def test_format_last_service_line_with_datetime() -> None:
    value = datetime(2026, 6, 9, 11, 30, tzinfo=UTC)

    assert format_last_service_line(value, _MSK) == "🛠️ Последнее обслуживание: 09.06.2026 14:30"


def test_format_last_service_line_no_data() -> None:
    assert format_last_service_line(None, _MSK) == "🛠️ Последнее обслуживание: нет данных"


def test_last_service_line_for_machine_reads_aggregate() -> None:
    submitted_at = datetime(2026, 6, 9, 11, 30, tzinfo=UTC)
    aggregate = MagicMock()
    aggregate.last_maintenance_completed_at.return_value = submitted_at
    deps = _deps_with_aggregate(aggregate)

    line = last_service_line_for_machine(deps, MachineId("vm-1"))

    assert line == "🛠️ Последнее обслуживание: 09.06.2026 14:30"
    aggregate.last_maintenance_completed_at.assert_called_once_with()


def test_last_service_line_for_machine_no_data() -> None:
    aggregate = MagicMock()
    aggregate.last_maintenance_completed_at.return_value = None
    deps = _deps_with_aggregate(aggregate)

    line = last_service_line_for_machine(deps, MachineId("vm-1"))

    assert line == "🛠️ Последнее обслуживание: нет данных"
