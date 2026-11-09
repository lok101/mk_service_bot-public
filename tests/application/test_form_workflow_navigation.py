from __future__ import annotations

import pytest

from src.application.form_workflow.models import (
    FormWorkflowAccepted,
    FormWorkflowIntegrationFailed,
    FormWorkflowInvalid,
    FormWorkflowRejected,
)
from src.application.form_workflow.navigation import resolve_navigation
from src.domain.ids import MachineId, TechnicianId


@pytest.mark.parametrize(
    "purpose",
    ["revision", "loading"],
)
def test_resolve_navigation_accepted_always_workspace(purpose: str) -> None:
    outcome = FormWorkflowAccepted(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose=purpose,  # type: ignore[arg-type]
        maintenance_screen="maintenance",
    )
    action = resolve_navigation(outcome)
    assert action.target_screen == "workspace"
    assert action.clear_session is True
    assert action.notify_in_chat is False
    assert "принята" in action.message_heading.lower()


def test_resolve_navigation_revision_rejected_returns_workspace() -> None:
    outcome = FormWorkflowRejected(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
        detail="Нужна предзагрузка",
    )
    action = resolve_navigation(outcome)
    assert action.target_screen == "workspace"
    assert action.message_heading == "Форма не принята"


def test_resolve_navigation_loading_rejected_returns_workspace() -> None:
    outcome = FormWorkflowRejected(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="loading",
        detail="Загрузка недоступна",
        maintenance_screen="admin_maintenance",
    )
    action = resolve_navigation(outcome)
    assert action.target_screen == "workspace"


def test_resolve_navigation_integration_failed() -> None:
    outcome = FormWorkflowIntegrationFailed(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="loading",
        detail="МойСклад недоступен",
    )
    action = resolve_navigation(outcome)
    assert action.message_heading == "Ошибка обработки ответа"
    assert action.target_screen == "workspace"


def test_resolve_navigation_invalid_without_purpose() -> None:
    outcome = FormWorkflowInvalid(detail="Токен недействителен")
    action = resolve_navigation(outcome)
    assert action.target_screen == "workspace"
    assert action.clear_session is True
    assert action.notify_in_chat is True
    assert action.form_error_in_window is False


def test_resolve_navigation_invalid_revision_stays_on_workspace() -> None:
    outcome = FormWorkflowInvalid(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        purpose="revision",
        detail="Revision form token has expired",
    )
    action = resolve_navigation(outcome)
    assert action.target_screen == "workspace"
    assert action.clear_session is False
    assert action.notify_in_chat is False
    assert action.form_error_in_window is True
