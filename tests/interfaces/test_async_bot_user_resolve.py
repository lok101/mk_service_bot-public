from __future__ import annotations

import asyncio
from unittest.mock import create_autospec, patch
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
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.deps import MachineListDeps


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


def test_resolve_bot_user_offloads_sync_resolver_to_thread() -> None:
    bot_user = SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=TechnicianId("tech-a"),
        company_roles=frozenset(),
    )
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.resolve.return_value = bot_user
    deps = _deps_with_resolver(resolver)

    with patch(
        "src.interfaces.telegram.machines.bot_user.asyncio.to_thread",
        side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs),
    ) as to_thread:
        result = asyncio.run(resolve_bot_user(deps, 1))

    assert result == bot_user
    to_thread.assert_called_once_with(resolver.resolve, 1)
