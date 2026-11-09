from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from tests.interfaces._machine_list_handler_helpers import (
    TEST_BOT_USER,
    button,
    callback_query,
    handlers,
)

from src.application.snack_loading.issue_inventory_link import (
    IssuedSnackInventoryLink,
    IssueSnackInventoryLink,
)
from src.application.snack_loading.ports import InventoryFormCell, SnackInventoryFormMode
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.testing.snack_loading_fakes import (
    FakeSnackInventoryCellsSource,
    FakeSnackInventoryFormFactory,
    FakeSnackInventoryFormsConfig,
    InMemorySnackInventoryFormRegistry,
)
from src.interfaces.telegram.machines.snack_inventory_workspace import (
    NO_SNACK_MATRIX_MESSAGE,
    issue_snack_inventory_link_for_mode,
    snack_inventory_workspace_flags,
)
from src.interfaces.telegram.machines.workspace_getter import build_workspace_payload

_MACHINE = MachineId("514")
_TECHNICIAN = TechnicianId("tech-1")
_CELLS = (InventoryFormCell("SnackA", 1, "SKU1"),)
_ISSUED_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _bot_user() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("10001"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=_TECHNICIAN,
        company_roles=frozenset(),
    )


def _caps() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=_TECHNICIAN,
        machine_id=_MACHINE,
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=False,
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        revision_form_link=None,
    )


def _issue_uc() -> IssueSnackInventoryLink:
    return IssueSnackInventoryLink(
        registry=InMemorySnackInventoryFormRegistry(),
        factory=FakeSnackInventoryFormFactory(),
        forms_settings=FakeSnackInventoryFormsConfig(),
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.snack",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )


def test_workspace_shows_snack_inventory_when_snapshots_exist() -> None:
    cells = FakeSnackInventoryCellsSource({_MACHINE.value: _CELLS})
    flags = snack_inventory_workspace_flags(
        machine_code=_MACHINE.value,
        cells_source=cells,
        issuer=_issue_uc(),
    )
    assert flags["snack_inventory_available"] is True
    assert flags["snack_inventory_show_stub"] is False

    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("UTC")
    deps.get_service_capabilities.execute.return_value = _caps()
    deps.issue_snack_inventory_link = _issue_uc()
    deps.snack_inventory_cells = cells
    manager = MagicMock()
    manager.dialog_data = {"machine_id": _MACHINE.value, "machine_name": "VM 514"}

    from src.interfaces.telegram.machines.maintenance_screen import MaintenanceScreenFlags

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=False,
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
            bot_user=_bot_user(),
            machine_id=_MACHINE,
        )

    assert payload["snack_inventory_available"] is True


def test_workspace_hides_or_rejects_snack_inventory_without_snapshots() -> None:
    cells = FakeSnackInventoryCellsSource({})
    flags = snack_inventory_workspace_flags(
        machine_code=_MACHINE.value,
        cells_source=cells,
        issuer=_issue_uc(),
    )
    assert flags["snack_inventory_available"] is False
    assert flags["snack_inventory_show_stub"] is True

    message = issue_snack_inventory_link_for_mode(
        machine_code=_MACHINE.value,
        mode="now",
        technician_id=_TECHNICIAN,
        cells_source=cells,
        issuer=_issue_uc(),
    )
    assert message == NO_SNACK_MATRIX_MESSAGE


@pytest.mark.parametrize("mode", ["now", "as_of"])
def test_workspace_mode_selection_calls_issue_link(mode: SnackInventoryFormMode) -> None:
    cells = FakeSnackInventoryCellsSource({_MACHINE.value: _CELLS})
    issuer = MagicMock(spec=IssueSnackInventoryLink)
    issuer.execute.return_value = IssuedSnackInventoryLink(
        form_id="form-1",
        form_url="https://forms.example/1?entry.snack=tok",
        fingerprint_id="fp",
    )

    result = issue_snack_inventory_link_for_mode(
        machine_code=_MACHINE.value,
        mode=mode,
        technician_id=_TECHNICIAN,
        cells_source=cells,
        issuer=issuer,
    )

    assert isinstance(result, IssuedSnackInventoryLink)
    assert result.form_url.startswith("https://forms.example/")
    issuer.execute.assert_called_once_with(
        machine_code=_MACHINE.value,
        mode=mode,
        cells=_CELLS,
        technician_id=_TECHNICIAN,
    )


def test_snack_inventory_mode_copy_failure_answers_alert() -> None:
    async def _run() -> None:
        list_handlers = handlers()
        issuer = MagicMock(spec=IssueSnackInventoryLink)
        issuer.execute.side_effect = RuntimeError("drive copy failed")
        cells = FakeSnackInventoryCellsSource({"vm-1": _CELLS})
        object.__setattr__(list_handlers.deps, "issue_snack_inventory_link", issuer)
        object.__setattr__(list_handlers.deps, "snack_inventory_cells", cells)

        callback = callback_query()
        manager = MagicMock()
        manager.dialog_data = {"machine_id": "vm-1", "machine_name": "VM 1"}
        manager.switch_to = AsyncMock()

        with patch(
            "src.interfaces.telegram.machines.handlers_snack_inventory.resolve_bot_user",
            new=AsyncMock(return_value=TEST_BOT_USER),
        ):
            await list_handlers.on_snack_inventory_now(callback, button(), manager)

        callback.answer.assert_awaited()
        kwargs = callback.answer.await_args.kwargs
        assert kwargs.get("show_alert") is True
        assert "форму" in callback.answer.await_args.args[0].lower()
        manager.switch_to.assert_not_awaited()

    asyncio.run(_run())
