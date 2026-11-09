from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.form_submissions.accept_flow import (
    AcceptFlow,
    FormSubmissionRejectedError,
    FormSubmissionValidationError,
)
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.machine_operations import (
    RegisterLoadingFromForm,
    RegisterLoadingFromFormCommand,
    RegisterRevisionFromForm,
    RegisterRevisionFromFormCommand,
)
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionSnapshot,
)
from src.domain.form_tokens import (
    RevisionFormTokenPayload,
    VerifiedInventoryFormToken,
)
from src.domain.ids import EventId, RevisionId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)
from src.domain.models import RevisionSource
from src.domain.quantities import QuantityInputMode
from src.domain.results import (
    LoadingNotAllowed,
    RevisionNotAllowed,
)

__all__ = [
    "AcceptInventoryFormSubmissionService",
    "AcceptRevisionFormSubmissionService",
    "FormSubmissionRejectedError",
    "FormSubmissionValidationError",
]


@beartype
@dataclass(frozen=True, slots=True)
class AcceptRevisionFormSubmissionService:
    form_submission_store: FormSubmissionStore
    register_revision_from_form: RegisterRevisionFromForm
    product_code_resolver: ProductCodeResolver
    form_token_field_name: str
    quantity_mode: QuantityInputMode | None = None
    allow_empty: bool | None = None
    apply_stock_range: bool | None = None
    allow_zero: bool | None = None

    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        revision_token: str,
        token_payload: RevisionFormTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> RevisionCompleted:
        def register() -> RevisionCompleted | RevisionNotAllowed:
            return self.register_revision_from_form.execute(
                RegisterRevisionFromFormCommand(
                    technician_id=token_payload.technician_id,
                    machine_id=token_payload.machine_id,
                    submitted_at=submitted_at,
                    form_id=form_id,
                    form_token=revision_token,
                ),
            )

        def mark_accepted(submission_id: str, result: RevisionCompleted) -> None:
            self.form_submission_store.mark_accepted(
                submission_id,
                event_id=result.event_id.value,
                occurred_at=result.occurred_at,
                revision_id=result.revision_id.value,
            )

        return self._flow().execute(
            form_id=form_id,
            submitted_at=submitted_at,
            form_token=revision_token,
            purpose="revision",
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            answers=answers,
            register=register,
            not_allowed_type=RevisionNotAllowed,
            mark_accepted=mark_accepted,
            event_from_snapshot=_revision_completed_from_snapshot,
        )

    @beartype
    def _flow(self) -> AcceptFlow:
        return AcceptFlow(
            form_submission_store=self.form_submission_store,
            product_code_resolver=self.product_code_resolver,
            form_token_field_name=self.form_token_field_name,
            quantity_mode=self.quantity_mode,
            allow_empty=self.allow_empty,
            apply_stock_range=self.apply_stock_range,
            allow_zero=self.allow_zero,
        )


@beartype
@dataclass(frozen=True, slots=True)
class AcceptInventoryFormSubmissionService:
    form_submission_store: FormSubmissionStore
    register_loading_from_form: RegisterLoadingFromForm
    product_code_resolver: ProductCodeResolver
    form_token_field_name: str
    quantity_mode: QuantityInputMode | None = None
    allow_empty: bool | None = None
    apply_stock_range: bool | None = None
    allow_zero: bool | None = None

    @beartype
    def execute_loading(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        token: str,
        token_payload: VerifiedInventoryFormToken,
        answers: tuple[FormAnswer, ...],
    ) -> LoadingSubmitted:
        def register() -> LoadingSubmitted | LoadingNotAllowed:
            return self.register_loading_from_form.execute(
                RegisterLoadingFromFormCommand(
                    technician_id=token_payload.technician_id,
                    machine_id=token_payload.machine_id,
                    submitted_at=submitted_at,
                    form_id=form_id,
                    form_token=token,
                ),
            )

        def mark_accepted(submission_id: str, result: LoadingSubmitted) -> None:
            self.form_submission_store.mark_accepted(
                submission_id,
                event_id=result.event_id.value,
                occurred_at=result.occurred_at,
            )

        return self._flow().execute(
            form_id=form_id,
            submitted_at=submitted_at,
            form_token=token,
            purpose="loading",
            technician_id=token_payload.technician_id,
            machine_id=token_payload.machine_id,
            answers=answers,
            register=register,
            not_allowed_type=LoadingNotAllowed,
            mark_accepted=mark_accepted,
            event_from_snapshot=_loading_submitted_from_snapshot,
        )

    @beartype
    def _flow(self) -> AcceptFlow:
        return AcceptFlow(
            form_submission_store=self.form_submission_store,
            product_code_resolver=self.product_code_resolver,
            form_token_field_name=self.form_token_field_name,
            quantity_mode=self.quantity_mode,
            allow_empty=self.allow_empty,
            apply_stock_range=self.apply_stock_range,
            allow_zero=self.allow_zero,
        )


@beartype
def _revision_completed_from_snapshot(
    snapshot: FormSubmissionSnapshot,
) -> RevisionCompleted:
    if snapshot.revision_id is None or snapshot.event_id is None or snapshot.occurred_at is None:
        raise ValueError(
            "Accepted revision snapshot must include revision_id, event_id and occurred_at",
        )
    if snapshot.machine_id is None:
        raise ValueError("Accepted revision snapshot must include machine_id")

    return RevisionCompleted(
        event_id=EventId(snapshot.event_id),
        revision_id=RevisionId(snapshot.revision_id),
        technician_id=snapshot.technician_id,
        machine_id=snapshot.machine_id,
        completed_at=snapshot.submitted_at,
        occurred_at=snapshot.occurred_at,
        source=RevisionSource.GOOGLE_FORM,
        form_id=snapshot.form_id,
        form_token=snapshot.form_token,
    )


@beartype
def _loading_submitted_from_snapshot(
    snapshot: FormSubmissionSnapshot,
) -> LoadingSubmitted:
    if snapshot.event_id is None or snapshot.occurred_at is None:
        raise ValueError("Accepted loading snapshot must include event_id and occurred_at")
    if snapshot.machine_id is None:
        raise ValueError("Accepted loading snapshot must include machine_id")

    return LoadingSubmitted(
        event_id=EventId(snapshot.event_id),
        technician_id=snapshot.technician_id,
        machine_id=snapshot.machine_id,
        submitted_at=snapshot.submitted_at,
        occurred_at=snapshot.occurred_at,
        form_id=snapshot.form_id,
        form_token=snapshot.form_token,
    )
