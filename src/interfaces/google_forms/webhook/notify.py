from __future__ import annotations

from beartype import beartype

from src.application.form_workflow import (
    FormWorkflowInvalid,
    FormWorkflowRejected,
)
from src.domain.form_submission import FormSubmissionPurpose
from src.domain.form_tokens import peek_machine_form_token
from src.domain.ids import MachineId, TechnicianId
from src.interfaces.google_forms.webhook.deps import GoogleFormsWebhookDeps


@beartype
async def _notify_rejection(
    deps: GoogleFormsWebhookDeps,
    *,
    technician_id: TechnicianId,
    machine_id: MachineId,
    purpose: FormSubmissionPurpose,
    message: str,
) -> None:
    await deps.form_workflow_notifier.notifier.notify(
        FormWorkflowRejected(
            technician_id=technician_id,
            machine_id=machine_id,
            purpose=purpose,
            detail=message,
        ),
    )


@beartype
async def _notify_validation_error(
    deps: GoogleFormsWebhookDeps,
    *,
    technician_id: TechnicianId,
    machine_id: MachineId,
    purpose: FormSubmissionPurpose,
    message: str,
) -> None:
    await deps.form_workflow_notifier.notifier.notify(
        FormWorkflowInvalid(
            technician_id=technician_id,
            machine_id=machine_id,
            purpose=purpose,
            detail=message,
        ),
    )


@beartype
async def _notify_invalid_token(
    deps: GoogleFormsWebhookDeps,
    *,
    token: str,
    secret: str,
    purpose: FormSubmissionPurpose | None,
    detail: str,
) -> None:
    peeked = peek_machine_form_token(token, secret)
    resolved_purpose = purpose
    if (
        resolved_purpose is None
        and peeked is not None
        and peeked.purpose
        in {
            "revision",
            "loading",
        }
    ):
        resolved_purpose = peeked.purpose  # type: ignore[assignment]

    await deps.form_workflow_notifier.notifier.notify(
        FormWorkflowInvalid(
            technician_id=peeked.technician_id if peeked is not None else None,
            machine_id=peeked.machine_id if peeked is not None else None,
            purpose=resolved_purpose,
            detail=detail,
        ),
    )


@beartype
async def _notify_warehouse_submission_error(
    deps: GoogleFormsWebhookDeps,
    *,
    technician_id: TechnicianId,
    reason: str,
) -> None:
    bot_user = deps.telegram_user_resolver.find_by_technician_id(technician_id)
    if bot_user is None:
        return
    await deps.direct_warehouse_chat_notifier.notify(
        technician_id=technician_id,
        reason=reason,
    )
