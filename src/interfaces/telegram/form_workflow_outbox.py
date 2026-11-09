from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_workflow import FormWorkflowAccepted, FormWorkflowNotifier
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)


@beartype
@dataclass(frozen=True, slots=True)
class FormWorkflowTelegramOutboxHandler:
    notifier: FormWorkflowNotifier

    @beartype
    async def process_revision(self, event: RevisionCompleted) -> None:
        await self.notifier.notify(
            FormWorkflowAccepted(
                technician_id=event.technician_id,
                machine_id=event.machine_id,
                purpose="revision",
            ),
        )

    @beartype
    async def process_loading(self, event: LoadingSubmitted) -> None:
        await self.notifier.notify(
            FormWorkflowAccepted(
                technician_id=event.technician_id,
                machine_id=event.machine_id,
                purpose="loading",
            ),
        )
