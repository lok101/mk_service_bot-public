from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, create_autospec
from zoneinfo import ZoneInfo

from aiogram.types import User

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
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.getters import (
    _INACTIVE_HEADLINE,
    build_machines_getter,
    inactive_user_payload,
)


def _inactive_technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("10005"),
        name="Роман",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=444555666,
        technician_id=TechnicianId("002"),
        company_roles=frozenset(),
    )


def _deps_with_resolver(resolver: TelegramUserResolver) -> MachineListDeps:
    return MachineListDeps(
        service_display_timezone=ZoneInfo("UTC"),
        service_day_end_hour=6,
        visit_store=InMemoryServiceVisitStore(),
        telegram_user_resolver=resolver,
        vending_machine_repository=create_autospec(VendingMachineRepository, instance=True),
        machine_operations=create_autospec(MachineOperationsRepository, instance=True),
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


def test_inactive_user_payload_shows_inactive_headline() -> None:
    bot_user = _inactive_technician()

    payload = inactive_user_payload(bot_user)

    assert payload["headline"] == _INACTIVE_HEADLINE
    assert payload["machines_count"] == 0
    assert payload["is_known_technician"] is False
    assert payload["user_is_active"] is False
    assert _INACTIVE_HEADLINE in str(payload["machines_screen_text"])


def test_machines_getter_returns_inactive_payload_for_inactive_user() -> None:
    bot_user = _inactive_technician()
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.resolve.return_value = bot_user
    deps = _deps_with_resolver(resolver)

    payload = asyncio.run(
        build_machines_getter(deps)(
            dialog_manager=MagicMock(),
            event_from_user=User(id=444555666, is_bot=False, first_name="Роман"),
        ),
    )

    assert payload["headline"] == _INACTIVE_HEADLINE
    assert payload["machines_count"] == 0
    resolver.resolve.assert_called_once_with(444555666)
