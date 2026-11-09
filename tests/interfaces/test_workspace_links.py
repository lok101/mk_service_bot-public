from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.ids import MachineId, TechnicianId
from src.domain.models import PrefilledFormLink
from src.domain.results import LoadingFormPrepared, ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.machines.workspace_links import provision_workspace_links


def _onboarding_caps() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="awaiting_handover",
        can_complete_revision=True,
        can_submit_loading=True,
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        revision_form_link=PrefilledFormLink(url="https://example.com/rev"),
    )


def _active_caps() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
        revision_form_link=None,
    )


def _test_bot_user() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("user-1"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=TechnicianId("001"),
        company_roles=frozenset(),
    )


def test_provision_handover_creates_revision_and_loading_urls() -> None:
    bot_user = _test_bot_user()
    deps = MagicMock()
    deps.get_service_capabilities.execute.return_value = _onboarding_caps()
    deps.create_loading_form.execute.return_value = LoadingFormPrepared(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        form_link=PrefilledFormLink(url="https://example.com/load-handover"),
    )
    session_store = MagicMock()
    deps.form_workflow_sessions = session_store

    manager = MagicMock()
    manager.dialog_data = {"machine_name": "VM 1"}

    with patch(
        "src.interfaces.telegram.machines.workspace_links.register_form_workflow_session",
        new=AsyncMock(),
    ) as register_session:
        asyncio.run(
            provision_workspace_links(
                deps,
                manager=manager,
                chat_id=1,
                telegram_user_id=1,
                technician_id=TechnicianId("001"),
                machine_id=MachineId("vm-1"),
                dialog_message_id=10,
                bot_user=bot_user,
            ),
        )

    assert manager.dialog_data["revision_form_url"] == "https://example.com/rev"
    assert manager.dialog_data["loading_form_url"] == "https://example.com/load-handover"
    assert register_session.call_count == 2
    purposes = [call.kwargs["purpose"] for call in register_session.call_args_list]
    assert purposes == ["revision", "loading"]
    assert all(call.kwargs["bot_user"] is bot_user for call in register_session.call_args_list)


def test_provision_active_clears_stale_revision_url() -> None:
    bot_user = _test_bot_user()
    deps = MagicMock()
    deps.get_service_capabilities.execute.return_value = _active_caps()
    deps.create_loading_form.execute.return_value = LoadingFormPrepared(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        form_link=PrefilledFormLink(url="https://example.com/load"),
    )
    session_store = MagicMock()
    deps.form_workflow_sessions = session_store

    manager = MagicMock()
    manager.dialog_data = {
        "machine_name": "VM 1",
        "revision_form_url": "https://stale/rev",
    }

    with patch(
        "src.interfaces.telegram.machines.workspace_links.register_form_workflow_session",
        new=AsyncMock(),
    ):
        asyncio.run(
            provision_workspace_links(
                deps,
                manager=manager,
                chat_id=1,
                telegram_user_id=1,
                technician_id=TechnicianId("001"),
                machine_id=MachineId("vm-1"),
                bot_user=bot_user,
            ),
        )

    assert "revision_form_url" not in manager.dialog_data
    assert manager.dialog_data["loading_form_url"] == "https://example.com/load"
    session_store.remove.assert_any_call(
        TechnicianId("001"),
        MachineId("vm-1"),
        "revision",
    )


def test_provision_responsible_clears_stale_revision_url() -> None:
    # responsible never keeps revision link (soft due_soon cut)
    bot_user = _test_bot_user()
    deps = MagicMock()
    deps.get_service_capabilities.execute.return_value = ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
        revision_form_link=None,
        revision_due_status="not_due",
    )
    deps.create_loading_form.execute.return_value = LoadingFormPrepared(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        form_link=PrefilledFormLink(url="https://example.com/load"),
    )
    session_store = MagicMock()
    deps.form_workflow_sessions = session_store

    manager = MagicMock()
    manager.dialog_data = {
        "machine_name": "VM 1",
        "revision_form_url": "https://stale/rev",
    }

    with patch(
        "src.interfaces.telegram.machines.workspace_links.register_form_workflow_session",
        new=AsyncMock(),
    ):
        asyncio.run(
            provision_workspace_links(
                deps,
                manager=manager,
                chat_id=1,
                telegram_user_id=1,
                technician_id=TechnicianId("001"),
                machine_id=MachineId("vm-1"),
                bot_user=bot_user,
            ),
        )

    assert "revision_form_url" not in manager.dialog_data
    assert manager.dialog_data["loading_form_url"] == "https://example.com/load"
