from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.form_workflow import MaintenanceWorkflowScreen
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowSession:
    chat_id: int
    telegram_user_id: int
    technician_id: TechnicianId
    machine_id: MachineId
    machine_name: str
    purpose: FormSubmissionPurpose
    maintenance_screen: MaintenanceWorkflowScreen
    registered_at: datetime
    dialog_message_id: int | None = None
