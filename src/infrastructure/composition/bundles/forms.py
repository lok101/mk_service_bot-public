from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_submissions.ports import FormSubmissionStore, TelegramUserResolver
from src.interfaces.google_forms.webhook import GoogleFormsWebhookDeps
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore


@beartype
@dataclass(frozen=True, slots=True)
class FormsBundle:
    submission_store: FormSubmissionStore
    workflow_session_store: FormWorkflowSessionStore
    telegram_user_resolver: TelegramUserResolver
    accept_revision: AcceptRevisionFormSubmissionService
    accept_inventory: AcceptInventoryFormSubmissionService
    webhook_deps: GoogleFormsWebhookDeps
