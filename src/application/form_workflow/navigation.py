from __future__ import annotations

from beartype import beartype

from src.application.form_workflow.models import (
    FormWorkflowAccepted,
    FormWorkflowIntegrationFailed,
    FormWorkflowInvalid,
    FormWorkflowOutcome,
    FormWorkflowRejected,
    NavigationAction,
)
from src.domain.form_submission import FormSubmissionPurpose


@beartype
def resolve_navigation(outcome: FormWorkflowOutcome) -> NavigationAction:
    if isinstance(outcome, FormWorkflowAccepted):
        return _navigation_for_accepted(outcome.purpose)
    if isinstance(outcome, FormWorkflowRejected):
        return _navigation_for_failure(
            outcome.purpose,
            heading="Форма не принята",
        )
    if isinstance(outcome, FormWorkflowInvalid):
        purpose = outcome.purpose
        if purpose is None:
            return NavigationAction(
                target_screen="workspace",
                message_heading="Форма не принята",
                clear_session=True,
            )
        return NavigationAction(
            target_screen="workspace",
            message_heading="",
            clear_session=False,
            notify_in_chat=False,
            form_error_in_window=True,
        )
    if isinstance(outcome, FormWorkflowIntegrationFailed):
        return _navigation_for_failure(
            outcome.purpose,
            heading="Ошибка обработки ответа",
        )
    raise TypeError(f"Unsupported form workflow outcome: {outcome!r}")


@beartype
def _navigation_for_accepted(
    purpose: FormSubmissionPurpose,
) -> NavigationAction:
    headings = {
        "revision": "Инвентаризация принята",
        "loading": "Загрузка принята",
    }
    return NavigationAction(
        target_screen="workspace",
        message_heading=headings[purpose],
        clear_session=True,
        notify_in_chat=False,
    )


@beartype
def _navigation_for_failure(
    purpose: FormSubmissionPurpose,
    *,
    heading: str,
) -> NavigationAction:
    return NavigationAction(
        target_screen="workspace",
        message_heading=heading,
        clear_session=True,
    )
