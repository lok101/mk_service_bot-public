from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import (
    RevisionFormTokenPayload,
    VerifiedInventoryFormToken,
)
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    RevisionCompleted,
)


@runtime_checkable
class AcceptRevisionFormSubmission(Protocol):
    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        revision_token: str,
        token_payload: RevisionFormTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> RevisionCompleted: ...


@runtime_checkable
class AcceptInventoryFormSubmission(Protocol):
    @beartype
    def execute_loading(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        token: str,
        token_payload: VerifiedInventoryFormToken,
        answers: tuple[FormAnswer, ...],
    ) -> LoadingSubmitted: ...
