from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.form_tokens import InventoryFormPurpose

MAX_FORM_TOKEN_LENGTH = 2_048


class FormAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    value: str = Field(max_length=10_000)


class GoogleFormRevisionSubmittedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_id: str
    submitted_at: datetime
    revision_token: str = Field(min_length=1, max_length=MAX_FORM_TOKEN_LENGTH)
    answers: list[FormAnswerPayload] = Field(min_length=1, max_length=200)


class GoogleFormRevisionSubmittedResponse(BaseModel):
    status: Literal["accepted"]
    event_id: str
    revision_id: str
    technician_id: str
    machine_id: str


class WarehouseInventorySubmittedResponse(BaseModel):
    status: Literal["accepted"]
    purpose: Literal["technician_warehouse_inventory"]
    event_id: str
    technician_id: str


class GoogleFormLoadingSubmittedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_id: str
    submitted_at: datetime
    token: str = Field(min_length=1, max_length=MAX_FORM_TOKEN_LENGTH)
    answers: list[FormAnswerPayload] = Field(min_length=1, max_length=200)


class GoogleFormLoadingSubmittedResponse(BaseModel):
    status: Literal["accepted"]
    purpose: InventoryFormPurpose
    event_id: str
    technician_id: str
    machine_id: str


class GoogleFormTechnicianWarehouseInventorySubmittedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_id: str
    submitted_at: datetime
    token: str = Field(min_length=1, max_length=MAX_FORM_TOKEN_LENGTH)
    answers: list[FormAnswerPayload] = Field(min_length=1, max_length=200)


class GoogleFormSnackInventorySubmittedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_id: str
    submitted_at: datetime
    token: str = Field(min_length=1, max_length=MAX_FORM_TOKEN_LENGTH)
    answers: list[FormAnswerPayload] = Field(min_length=1, max_length=200)


class SnackInventorySubmittedResponse(BaseModel):
    status: Literal["accepted"]
    purpose: Literal["snack_inventory_now", "snack_inventory_as_of"]
    inventory_id: str
    machine_code: str


class MicromarketInventorySubmittedResponse(BaseModel):
    status: Literal["accepted"]
    purpose: Literal["micromarket_inventory_now", "micromarket_inventory_as_of"]
    inventory_id: str
    machine_code: str
