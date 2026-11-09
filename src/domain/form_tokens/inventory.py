from __future__ import annotations

from collections.abc import Callable
from typing import cast

from beartype import beartype

from src.domain.form_tokens.codec import _create_machine_form_token, _verify_machine_form_token
from src.domain.form_tokens.types import (
    InventoryFormPurpose,
    InventoryFormTokenPayload,
    VerifiedInventoryFormToken,
)

_INVENTORY_PURPOSES = frozenset({"loading"})


@beartype
def create_loading_form_token(
    payload: InventoryFormTokenPayload,
    secret: str,
) -> str:
    return _create_inventory_form_token(payload, purpose="loading", secret=secret)


@beartype
def _create_inventory_form_token(
    payload: InventoryFormTokenPayload,
    *,
    purpose: InventoryFormPurpose,
    secret: str,
) -> str:
    if not secret:
        raise ValueError("Inventory form token secret must not be empty")

    return _create_machine_form_token(
        technician_id=payload.technician_id,
        machine_id=payload.machine_id,
        issued_at=payload.issued_at,
        nonce=payload.nonce,
        purpose=purpose,
        secret=secret,
    )


@beartype
def verify_inventory_form_token(
    token: str,
    secret: str,
    *,
    max_age_hours: float | None = None,
    expected_purpose: InventoryFormPurpose | None = None,
) -> VerifiedInventoryFormToken:
    parsed = _verify_machine_form_token(
        token=token,
        secret=secret,
        form_name="Inventory",
        expected_purpose=None,
        allow_missing_purpose=False,
        allowed_purposes=_INVENTORY_PURPOSES,
        max_age_hours=max_age_hours,
    )
    if parsed.purpose is None or parsed.purpose not in _INVENTORY_PURPOSES:
        raise ValueError("Inventory form token purpose is invalid")
    if expected_purpose is not None and parsed.purpose != expected_purpose:
        raise ValueError("Inventory form token purpose is invalid")

    return VerifiedInventoryFormToken(
        purpose=cast(InventoryFormPurpose, parsed.purpose),
        technician_id=parsed.technician_id,
        machine_id=parsed.machine_id,
        issued_at=parsed.issued_at,
        nonce=parsed.nonce,
    )


@beartype
def build_verify_inventory_form_token(
    *,
    max_age_hours: float,
) -> Callable[[str, str], VerifiedInventoryFormToken]:
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")

    def _verify(token: str, secret: str) -> VerifiedInventoryFormToken:
        return verify_inventory_form_token(
            token,
            secret,
            max_age_hours=max_age_hours,
        )

    return _verify
