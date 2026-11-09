from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.telegram.form_workflow.models import FormWorkflowSession


@runtime_checkable
class FormWorkflowSessionStore(Protocol):
    @beartype
    def upsert(self, session: FormWorkflowSession) -> None: ...

    @beartype
    def find(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None: ...

    @beartype
    def remove(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None: ...
