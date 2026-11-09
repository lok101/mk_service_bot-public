from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId
from src.domain.product_catalog import ProductUnit

FormSubmissionPurpose = Literal[
    "revision",
    "loading",
    "technician_warehouse_inventory",
]
FormSubmissionStatus = Literal["pending", "accepted", "rejected"]

_WAREHOUSE_INVENTORY_PURPOSE: FormSubmissionPurpose = "technician_warehouse_inventory"


@beartype
@dataclass(frozen=True, slots=True)
class FormAnswer:
    title: str
    value: str

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Form answer title must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class FrozenProductSpec:
    product_code: str
    name: str
    unit: ProductUnit
    pack_size: Decimal | None
    moysklad_quantity_factor: Decimal

    def __post_init__(self) -> None:
        if not self.product_code:
            raise ValueError("product_code must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if self.moysklad_quantity_factor <= 0:
            raise ValueError("moysklad_quantity_factor must be positive")


@beartype
@dataclass(frozen=True, slots=True)
class FrozenInventoryLine:
    form_title: str
    product_spec: FrozenProductSpec
    quantity: Decimal

    def __post_init__(self) -> None:
        if not self.form_title.strip():
            raise ValueError("form_title must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class FormSubmissionSnapshot:
    submission_id: str
    form_token: str
    form_id: str
    purpose: FormSubmissionPurpose
    technician_id: TechnicianId
    machine_id: MachineId | None
    submitted_at: datetime
    answers: tuple[FormAnswer, ...]
    validated_lines: tuple[FrozenInventoryLine, ...]
    status: FormSubmissionStatus
    event_id: str | None = None
    occurred_at: datetime | None = None
    revision_id: str | None = None
    rejection_reason: str | None = None
    warehouse_inventory_baseline: bool | None = None

    def __post_init__(self) -> None:
        if not self.submission_id:
            raise ValueError("submission_id must not be empty")
        if not self.form_token:
            raise ValueError("form_token must not be empty")
        if not self.form_id:
            raise ValueError("form_id must not be empty")
        if self.purpose == _WAREHOUSE_INVENTORY_PURPOSE:
            if self.machine_id is not None:
                raise ValueError(
                    "technician_warehouse_inventory submission must not have machine_id"
                )
        elif self.machine_id is None:
            raise ValueError("machine_id is required for non-warehouse submissions")
        if not self.answers:
            raise ValueError("answers must not be empty")
        if self.status == "accepted" and not self.event_id:
            raise ValueError("accepted submission must have event_id")
        if self.status == "accepted" and self.occurred_at is None:
            raise ValueError("accepted submission must have occurred_at")
        if (
            self.warehouse_inventory_baseline is not None
            and self.purpose != _WAREHOUSE_INVENTORY_PURPOSE
        ):
            raise ValueError(
                "warehouse_inventory_baseline is only allowed for warehouse submissions"
            )
