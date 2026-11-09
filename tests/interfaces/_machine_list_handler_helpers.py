from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec
from zoneinfo import ZoneInfo

from aiogram.types import CallbackQuery
from aiogram_dialog.widgets.kbd import Button

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
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ResponsibilityPhase, ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.handlers import MachineListHandlers

TEST_BOT_USER = SystemUser(
    user_id=SystemUserId("10001"),
    name="Test",
    role=BotRole.TECHNICIAN,
    is_active=True,
    telegram_user_id=1,
    technician_id=TechnicianId("001"),
    company_roles=frozenset(),
)


def caps(
    *,
    responsibility_phase: ResponsibilityPhase = "responsible",
    can_complete_revision: bool = False,
    can_submit_loading: bool = True,
    can_submit_loading_photos: bool = True,
    can_complete_maintenance: bool = True,
    loading_completed: bool = True,
    loading_photos_completed: bool = False,
    maintenance_completed_today: bool = False,
) -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase=responsibility_phase,
        can_complete_revision=can_complete_revision,
        can_submit_loading=can_submit_loading,
        can_submit_loading_photos=can_submit_loading_photos,
        can_complete_maintenance=can_complete_maintenance,
        revision_form_link=None,
        loading_completed=loading_completed,
        loading_photos_completed=loading_photos_completed,
        maintenance_completed_today=maintenance_completed_today,
    )


def callback_query(*, with_message: bool = False) -> CallbackQuery:
    callback = create_autospec(CallbackQuery, instance=True)
    callback.from_user = MagicMock()
    callback.from_user.id = 1
    callback.answer = AsyncMock()
    if with_message:
        callback.message = MagicMock()
        callback.message.chat = MagicMock()
        callback.message.chat.id = 12345
        callback.message.message_id = 10
    else:
        callback.message = None
    return callback


def button() -> Button:
    return create_autospec(Button, instance=True)


def handlers() -> MachineListHandlers:
    get_service_capabilities = create_autospec(GetServiceCapabilities, instance=True)
    get_service_capabilities.execute.return_value = caps()
    deps = MachineListDeps(
        service_display_timezone=ZoneInfo("Europe/Moscow"),
        service_day_end_hour=6,
        visit_store=InMemoryServiceVisitStore(),
        telegram_user_resolver=create_autospec(TelegramUserResolver, instance=True),
        vending_machine_repository=create_autospec(VendingMachineRepository, instance=True),
        machine_operations=create_autospec(MachineOperationsRepository, instance=True),
        list_available_machines=create_autospec(ListAvailableMachines, instance=True),
        get_service_capabilities=get_service_capabilities,
        complete_maintenance=create_autospec(CompleteMaintenance, instance=True),
        create_loading_form=create_autospec(CreateLoadingForm, instance=True),
        form_workflow_sessions=create_autospec(FormWorkflowSessionStore, instance=True),
        accept_loading_photos=create_autospec(AcceptLoadingPhotosService, instance=True),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
        maintenance_cooldown_minutes=20,
    )
    return MachineListHandlers(deps)
