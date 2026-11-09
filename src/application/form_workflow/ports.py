from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.form_workflow.models import FormWorkflowOutcome


@runtime_checkable
class FormWorkflowNotifier(Protocol):
    @beartype
    async def notify(self, outcome: FormWorkflowOutcome) -> None: ...
