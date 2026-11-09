from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    CoffeeFormTokenPayload,
    RevisionFormTokenPayload,
    VerifiedInventoryFormToken,
)
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted


@beartype
@dataclass(frozen=True, slots=True)
class AcceptCoffeeRevisionFieldForm:
    accept_revision: AcceptRevisionFormSubmissionService

    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        token: str,
        token_payload: CoffeeFormTokenPayload,
        answers: tuple[FormAnswer, ...],
        purpose: str = "revision",
    ) -> RevisionCompleted:
        del purpose
        return self.accept_revision.execute(
            form_id=form_id,
            submitted_at=submitted_at,
            revision_token=token,
            token_payload=RevisionFormTokenPayload(
                technician_id=token_payload.technician_id,
                machine_id=token_payload.machine_id,
                issued_at=token_payload.issued_at,
                nonce=token_payload.nonce,
            ),
            answers=answers,
        )


@beartype
@dataclass(frozen=True, slots=True)
class AcceptCoffeeLoadingFieldForm:
    accept_loading: AcceptInventoryFormSubmissionService

    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        token: str,
        token_payload: CoffeeFormTokenPayload,
        answers: tuple[FormAnswer, ...],
        purpose: str = "loading",
    ) -> LoadingSubmitted:
        del purpose
        return self.accept_loading.execute_loading(
            form_id=form_id,
            submitted_at=submitted_at,
            token=token,
            token_payload=VerifiedInventoryFormToken(
                purpose="loading",
                technician_id=token_payload.technician_id,
                machine_id=token_payload.machine_id,
                issued_at=token_payload.issued_at,
                nonce=token_payload.nonce,
            ),
            answers=answers,
        )
