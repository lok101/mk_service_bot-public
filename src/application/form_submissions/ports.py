from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.product_catalog import ProductSpec
from src.domain.system_user import SystemUser

ExternalSideEffectStatus = Literal["processing", "succeeded", "failed"]


class ExternalSideEffectInProgressError(RuntimeError):
    """Raised when another worker owns a side effect that has not completed yet."""


@beartype
@dataclass(frozen=True, slots=True)
class ExternalSideEffectClaim:
    claimed: bool
    status: ExternalSideEffectStatus
    external_code: str
    previous_status: ExternalSideEffectStatus | None = None
    external_id: str | None = None


@runtime_checkable
class FormSubmissionStore(Protocol):
    @beartype
    def save_pending(
        self,
        *,
        form_token: str,
        form_id: str,
        purpose: FormSubmissionPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId | None,
        submitted_at: datetime,
        answers: tuple[FormAnswer, ...],
        validated_lines: tuple[FrozenInventoryLine, ...],
    ) -> FormSubmissionSnapshot: ...

    @beartype
    def mark_accepted(
        self,
        submission_id: str,
        *,
        event_id: str,
        occurred_at: datetime,
        revision_id: str | None = None,
        warehouse_inventory_baseline: bool | None = None,
    ) -> FormSubmissionSnapshot: ...

    @beartype
    def mark_rejected(
        self,
        submission_id: str,
        *,
        reason: str,
    ) -> FormSubmissionSnapshot: ...

    @beartype
    def get_by_event_id(self, event_id: str) -> FormSubmissionSnapshot | None: ...

    @beartype
    def get_by_form_token(
        self,
        form_token: str,
        purpose: FormSubmissionPurpose,
    ) -> FormSubmissionSnapshot | None: ...


@runtime_checkable
class ProductCodeResolver(Protocol):
    @beartype
    def resolve_by_name(self, product_name: str) -> ProductSpec: ...


@runtime_checkable
class ExternalSideEffectRegistry(Protocol):
    @beartype
    def claim(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_code: str,
    ) -> ExternalSideEffectClaim: ...

    @beartype
    def mark_succeeded(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_id: str | None = None,
    ) -> None: ...

    @beartype
    def mark_failed(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        error_message: str,
    ) -> None: ...

    @beartype
    def count_settlement_related(self) -> int: ...

    @beartype
    def delete_settlement_related(self) -> int: ...


@runtime_checkable
class TelegramUserResolver(Protocol):
    @beartype
    def resolve(self, telegram_user_id: int) -> SystemUser | None: ...

    @beartype
    def find_by_technician_id(self, technician_id: TechnicianId) -> SystemUser | None: ...
