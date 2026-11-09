from __future__ import annotations

from beartype import beartype
from fastapi import HTTPException
from pydantic import ValidationError

from src.interfaces.google_forms.webhook.schemas import (
    GoogleFormLoadingSubmittedRequest,
    GoogleFormRevisionSubmittedRequest,
    GoogleFormSnackInventorySubmittedRequest,
    GoogleFormTechnicianWarehouseInventorySubmittedRequest,
)


@beartype
def _parse_revision_payload(body: bytes) -> GoogleFormRevisionSubmittedRequest:
    try:
        return GoogleFormRevisionSubmittedRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


@beartype
def _parse_loading_payload(body: bytes) -> GoogleFormLoadingSubmittedRequest:
    try:
        return GoogleFormLoadingSubmittedRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


@beartype
def _parse_warehouse_inventory_payload(
    body: bytes,
) -> GoogleFormTechnicianWarehouseInventorySubmittedRequest:
    try:
        return GoogleFormTechnicianWarehouseInventorySubmittedRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


@beartype
def _parse_snack_inventory_payload(
    body: bytes,
) -> GoogleFormSnackInventorySubmittedRequest:
    try:
        return GoogleFormSnackInventorySubmittedRequest.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
