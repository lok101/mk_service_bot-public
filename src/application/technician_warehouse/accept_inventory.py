"""Accept warehouse inventory form submissions into TechnicianWarehouse.

For ``purpose=technician_warehouse_inventory``, accepted snapshot ``revision_id``
stores the domain ``inventory_id`` (field overload until a dedicated schema field).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from beartype import beartype

from src.application.form_submissions import (
    FormSubmissionValidationError,
    QuantityValidationError,
    parse_and_build_frozen_inventory_lines,
)
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.technician_warehouse.ports import TechnicianWarehouseCommandExecutor
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionPurpose,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
)
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.ids import EventId
from src.domain.quantities import packages_to_base_quantity
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted


@beartype
def _build_frozen_inventory_lines(
    *,
    product_code_resolver: ProductCodeResolver,
    form_token_field_name: str,
    answers: tuple[FormAnswer, ...],
    mode_purpose: FormSubmissionPurpose | str,
    allow_empty: bool | None = None,
) -> tuple[FrozenInventoryLine, ...]:
    try:
        return parse_and_build_frozen_inventory_lines(
            product_code_resolver=product_code_resolver,
            form_token_field_name=form_token_field_name,
            answers=answers,
            mode_purpose=mode_purpose,
            allow_empty=allow_empty,
        )
    except ValueError as error:
        raise FormSubmissionValidationError(str(error)) from error
    except QuantityValidationError as error:
        raise FormSubmissionValidationError(str(error)) from error


@beartype
def _packages_lines_to_base(
    validated_lines: tuple[FrozenInventoryLine, ...],
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for line in validated_lines:
        pack_size = line.product_spec.pack_size
        if pack_size is None or pack_size <= 0:
            raise FormSubmissionValidationError(
                f"Pack size must be configured for product {line.product_spec.name!r}",
            )
        result[line.product_spec.product_code] = packages_to_base_quantity(
            packages=line.quantity,
            pack_size=pack_size,
        )
    return result


@beartype
def _to_warehouse_lines(
    validated_lines: tuple[FrozenInventoryLine, ...],
) -> dict[str, Decimal]:
    return _packages_lines_to_base(validated_lines)


@beartype
def _event_from_snapshot(
    snapshot: FormSubmissionSnapshot,
) -> TechnicianWarehouseInventoryCounted:
    if snapshot.event_id is None or snapshot.occurred_at is None:
        raise ValueError("Accepted warehouse snapshot must include event_id and occurred_at")

    base_by_sku = _packages_lines_to_base(snapshot.validated_lines)
    lines = tuple(sorted(base_by_sku.items()))
    inventory_id = snapshot.revision_id or ""
    baseline = (
        snapshot.warehouse_inventory_baseline
        if snapshot.warehouse_inventory_baseline is not None
        else False
    )

    return TechnicianWarehouseInventoryCounted(
        event_id=EventId(snapshot.event_id),
        technician_id=snapshot.technician_id,
        occurred_at=snapshot.occurred_at,
        inventory_id=inventory_id,
        form_token=snapshot.form_token,
        counted_at=snapshot.submitted_at,
        lines=lines,
        baseline=baseline,
    )


@beartype
@dataclass(frozen=True, slots=True)
class AcceptTechnicianWarehouseInventoryService:
    form_submission_store: FormSubmissionStore
    product_code_resolver: ProductCodeResolver
    form_token_field_name: str
    executor: TechnicianWarehouseCommandExecutor
    allow_empty: bool | None = None

    @beartype
    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted:
        purpose: FormSubmissionPurpose = "technician_warehouse_inventory"
        existing = self.form_submission_store.get_by_form_token(form_token, purpose)
        if existing is not None and existing.status == "accepted":
            return _event_from_snapshot(existing)

        try:
            validated_lines = _build_frozen_inventory_lines(
                product_code_resolver=self.product_code_resolver,
                form_token_field_name=self.form_token_field_name,
                answers=answers,
                mode_purpose=purpose,
                allow_empty=self.allow_empty,
            )
        except FormSubmissionValidationError as error:
            snapshot = self.form_submission_store.save_pending(
                form_token=form_token,
                form_id=form_id,
                purpose=purpose,
                technician_id=token_payload.technician_id,
                machine_id=None,
                submitted_at=submitted_at,
                answers=answers,
                validated_lines=(),
            )
            self.form_submission_store.mark_rejected(
                snapshot.submission_id,
                reason=error.reason,
            )
            raise

        snapshot = self.form_submission_store.save_pending(
            form_token=form_token,
            form_id=form_id,
            purpose=purpose,
            technician_id=token_payload.technician_id,
            machine_id=None,
            submitted_at=submitted_at,
            answers=answers,
            validated_lines=validated_lines,
        )
        event = self.executor.execute(
            token_payload.technician_id,
            lambda warehouse: warehouse.count_inventory(
                inventory_id=str(uuid4()),
                form_token=form_token,
                counted_at=submitted_at,
                actual_by_sku=_to_warehouse_lines(validated_lines),
                baseline=False,
            ),
        )
        self.form_submission_store.mark_accepted(
            snapshot.submission_id,
            event_id=event.event_id.value,
            occurred_at=event.occurred_at,
            revision_id=event.inventory_id,
            warehouse_inventory_baseline=event.baseline,
        )
        return event
