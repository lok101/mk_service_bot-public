from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.domain.form_submission import FormSubmissionPurpose
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.telegram.form_workflow import FormWorkflowSession


@beartype
@dataclass
class InMemoryFormWorkflowSessionStore:
    _sessions: dict[tuple[str, str, str], FormWorkflowSession] = field(
        default_factory=dict,
    )

    @beartype
    def upsert(self, session: FormWorkflowSession) -> None:
        key = _session_key(
            session.technician_id,
            session.machine_id,
            session.purpose,
        )
        self._sessions[key] = session

    @beartype
    def find(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None:
        return self._sessions.get(_session_key(technician_id, machine_id, purpose))

    @beartype
    def remove(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
        purpose: FormSubmissionPurpose,
    ) -> FormWorkflowSession | None:
        return self._sessions.pop(_session_key(technician_id, machine_id, purpose), None)


@beartype
def _session_key(
    technician_id: TechnicianId,
    machine_id: MachineId,
    purpose: FormSubmissionPurpose,
) -> tuple[str, str, str]:
    return (technician_id.value, machine_id.value, purpose)
