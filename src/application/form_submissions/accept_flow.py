from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from beartype import beartype

from src.application.form_submissions.inventory_snapshot import (
    parse_and_build_frozen_inventory_lines,
)
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.form_submissions.quantity_validation import QuantityValidationError
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.quantities import QuantityInputMode


class FormSubmissionRejectedError(Exception):
    @beartype
    def __init__(self, reason: str) -> None:
        if not reason:
            raise ValueError("rejection reason must not be empty")
        self.reason = reason
        super().__init__(reason)


class FormSubmissionValidationError(Exception):
    @beartype
    def __init__(self, reason: str) -> None:
        if not reason:
            raise ValueError("rejection reason must not be empty")
        self.reason = reason
        super().__init__(reason)


class _Rejectable(Protocol):
    reason: str


@beartype
def _build_frozen_inventory_lines(
    *,
    product_code_resolver: ProductCodeResolver,
    form_token_field_name: str,
    answers: tuple[FormAnswer, ...],
    mode_purpose: FormSubmissionPurpose | str,
    quantity_mode: QuantityInputMode | None = None,
    allow_empty: bool | None = None,
    apply_stock_range: bool | None = None,
    allow_zero: bool | None = None,
) -> tuple[FrozenInventoryLine, ...]:
    try:
        return parse_and_build_frozen_inventory_lines(
            product_code_resolver=product_code_resolver,
            form_token_field_name=form_token_field_name,
            answers=answers,
            mode_purpose=mode_purpose,
            quantity_mode=quantity_mode,
            allow_empty=allow_empty,
            apply_stock_range=apply_stock_range,
            allow_zero=allow_zero,
        )
    except ValueError as error:
        raise FormSubmissionValidationError(str(error)) from error
    except QuantityValidationError as error:
        raise FormSubmissionValidationError(str(error)) from error


@beartype
@dataclass(frozen=True, slots=True)
class AcceptFlow:
    form_submission_store: FormSubmissionStore
    product_code_resolver: ProductCodeResolver
    form_token_field_name: str
    quantity_mode: QuantityInputMode | None = None
    allow_empty: bool | None = None
    apply_stock_range: bool | None = None
    allow_zero: bool | None = None

    @beartype
    def execute[EventT, NotAllowedT](
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        purpose: FormSubmissionPurpose,
        technician_id: TechnicianId,
        machine_id: MachineId,
        answers: tuple[FormAnswer, ...],
        register: Callable[[], EventT | NotAllowedT],
        not_allowed_type: type[NotAllowedT],
        mark_accepted: Callable[[str, EventT], None],
        event_from_snapshot: Callable[[FormSubmissionSnapshot], EventT],
    ) -> EventT:
        existing = self.form_submission_store.get_by_form_token(form_token, purpose)
        if existing is not None and existing.status == "accepted":
            return event_from_snapshot(existing)

        validated_lines = _build_frozen_inventory_lines(
            product_code_resolver=self.product_code_resolver,
            form_token_field_name=self.form_token_field_name,
            answers=answers,
            mode_purpose=purpose,
            quantity_mode=self.quantity_mode,
            allow_empty=self.allow_empty,
            apply_stock_range=self.apply_stock_range,
            allow_zero=self.allow_zero,
        )
        snapshot = self.form_submission_store.save_pending(
            form_token=form_token,
            form_id=form_id,
            purpose=purpose,
            technician_id=technician_id,
            machine_id=machine_id,
            submitted_at=submitted_at,
            answers=answers,
            validated_lines=validated_lines,
        )
        result = register()
        if isinstance(result, not_allowed_type):
            rejected = cast("_Rejectable", result)
            self.form_submission_store.mark_rejected(
                snapshot.submission_id,
                reason=rejected.reason,
            )
            raise FormSubmissionRejectedError(rejected.reason)
        mark_accepted(snapshot.submission_id, cast(EventT, result))
        return cast(EventT, result)
