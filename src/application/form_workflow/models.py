from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from beartype import beartype

from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId

FormWorkflowScreen = Literal[
    "workspace",
    "onboarding",
    "maintenance",
    "admin_maintenance",
    "revision_form",
    "loading_form",
]

MaintenanceWorkflowScreen = Literal["maintenance", "admin_maintenance"]

FormWorkflowOutcomeKind = Literal["accepted", "rejected", "invalid", "integration_failed"]


@beartype
@dataclass(frozen=True, slots=True)
class NavigationAction:
    target_screen: FormWorkflowScreen
    message_heading: str
    clear_session: bool
    notify_in_chat: bool = True
    form_error_in_window: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowAccepted:
    technician_id: TechnicianId
    machine_id: MachineId
    purpose: FormSubmissionPurpose
    maintenance_screen: MaintenanceWorkflowScreen = "maintenance"
    detail: str = ""
    kind: Literal["accepted"] = "accepted"


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowRejected:
    technician_id: TechnicianId
    machine_id: MachineId
    purpose: FormSubmissionPurpose
    detail: str
    maintenance_screen: MaintenanceWorkflowScreen = "maintenance"
    kind: Literal["rejected"] = "rejected"


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowInvalid:
    kind: Literal["invalid"] = "invalid"
    technician_id: TechnicianId | None = None
    machine_id: MachineId | None = None
    purpose: FormSubmissionPurpose | None = None
    maintenance_screen: MaintenanceWorkflowScreen = "maintenance"
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.detail:
            raise ValueError("detail must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowIntegrationFailed:
    technician_id: TechnicianId
    machine_id: MachineId
    purpose: FormSubmissionPurpose
    detail: str
    maintenance_screen: MaintenanceWorkflowScreen = "maintenance"
    kind: Literal["integration_failed"] = "integration_failed"


type FormWorkflowOutcome = (
    FormWorkflowAccepted
    | FormWorkflowRejected
    | FormWorkflowInvalid
    | FormWorkflowIntegrationFailed
)


@beartype
def utc_now() -> datetime:
    return datetime.now(tz=UTC)
