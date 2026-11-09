from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.machines.workspace_getter import build_workspace_payload

_TEST_BOT_USER = SystemUser(
    user_id=SystemUserId("10001"),
    name="Test",
    role=BotRole.TECHNICIAN,
    is_active=True,
    telegram_user_id=1,
    technician_id=TechnicianId("001"),
    company_roles=frozenset(),
)


def _caps_active() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
        revision_form_link=None,
        loading_completed=False,
    )


def _deps_mock() -> MagicMock:
    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("Europe/Moscow")
    deps.issue_snack_inventory_link = None
    deps.snack_inventory_cells = None
    return deps


def test_getter_hides_onboarding_urls_when_active_despite_stale_dialog_data() -> None:
    deps = _deps_mock()
    deps.get_service_capabilities.execute.return_value = _caps_active()
    deps.machine_operations.get.return_value = MagicMock(
        last_maintenance_completed_at=MagicMock(return_value=None),
    )
    manager = MagicMock()
    manager.dialog_data = {
        "machine_id": "vm-1",
        "machine_name": "VM 1",
        "revision_form_url": "https://stale.example/rev",
        "loading_form_url": "https://example.com/load",
    }
    from src.interfaces.telegram.machines.maintenance_screen import (
        MaintenanceScreenFlags,
    )

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_TEST_BOT_USER,
            machine_id=MachineId("vm-1"),
        )

    assert payload["revision_has_url"] is False
    assert payload["loading_has_url"] is True
    assert payload["loading_photos_onboarding_stub"] is False
    assert payload["loading_photos_responsible_stub"] is False
    assert payload["can_submit_loading_photos"] is True
    assert payload["loading_photos_completed"] is False


def test_getter_shows_loading_photos_onboarding_stub() -> None:
    deps = _deps_mock()
    deps.get_service_capabilities.execute.return_value = ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="awaiting_handover",
        can_complete_revision=True,
        can_submit_loading=False,
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        revision_form_link=None,
    )
    deps.machine_operations.get.return_value = MagicMock(
        last_maintenance_completed_at=MagicMock(return_value=None),
    )
    manager = MagicMock()
    manager.dialog_data = {
        "machine_id": "vm-1",
        "machine_name": "VM 1",
        "revision_form_url": "https://example.com/rev",
    }
    from src.interfaces.telegram.machines.maintenance_screen import (
        MaintenanceScreenFlags,
    )

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=False,
                show_maintenance_back=True,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_TEST_BOT_USER,
            machine_id=MachineId("vm-1"),
        )

    assert payload["loading_photos_onboarding_stub"] is True
    assert payload["loading_photos_responsible_stub"] is False
    assert payload["can_submit_loading_photos"] is False


def test_getter_revision_not_due_today_uses_checked_at_in_screen_text() -> None:
    checked_at = datetime(2026, 5, 25, 9, 0, tzinfo=UTC)
    expires_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    deps = _deps_mock()
    deps.get_service_capabilities.execute.return_value = ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
        revision_form_link=None,
        loading_completed=False,
        revision_due_status="not_due",
        responsibility_expires_at=expires_at,
    )
    deps.machine_operations.get.return_value = MagicMock(
        last_maintenance_completed_at=MagicMock(return_value=None),
    )
    manager = MagicMock()
    manager.dialog_data = {
        "machine_id": "vm-1",
        "machine_name": "VM 1",
        "loading_form_url": "https://example.com/load",
    }
    from src.interfaces.telegram.machines.maintenance_screen import (
        MaintenanceScreenFlags,
    )

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        payload = build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_TEST_BOT_USER,
            machine_id=MachineId("vm-1"),
            checked_at=checked_at,
        )

    assert "Инвентаризация: 25.05.2026" in str(payload["workspace_screen_text"])
