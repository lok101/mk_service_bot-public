from __future__ import annotations

from dataclasses import dataclass

from src.application.form_workflow.ports import FormWorkflowNotifier


@dataclass(slots=True)
class FormWorkflowNotifierRef:
    """Mutable holder so webhook deps stay valid after Telegram bot registration."""

    notifier: FormWorkflowNotifier
