from __future__ import annotations

from beartype import beartype

from src.domain.form_tokens.codec import (
    _create_technician_only_form_token,
    _verify_technician_only_form_token,
)
from src.domain.form_tokens.types import TechnicianWarehouseInventoryTokenPayload

_WAREHOUSE_INVENTORY_PURPOSE = "technician_warehouse_inventory"


@beartype
def create_technician_warehouse_inventory_token(
    payload: TechnicianWarehouseInventoryTokenPayload,
    secret: str,
) -> str:
    if not secret:
        raise ValueError("Technician warehouse inventory form token secret must not be empty")

    return _create_technician_only_form_token(
        technician_id=payload.technician_id,
        issued_at=payload.issued_at,
        nonce=payload.nonce,
        purpose=_WAREHOUSE_INVENTORY_PURPOSE,
        secret=secret,
    )


@beartype
def verify_technician_warehouse_inventory_token(
    token: str,
    secret: str,
    *,
    max_age_hours: float | None = None,
) -> TechnicianWarehouseInventoryTokenPayload:
    parsed = _verify_technician_only_form_token(
        token=token,
        secret=secret,
        form_name="Technician warehouse inventory",
        expected_purpose=_WAREHOUSE_INVENTORY_PURPOSE,
        max_age_hours=max_age_hours,
    )
    return TechnicianWarehouseInventoryTokenPayload(
        technician_id=parsed.technician_id,
        issued_at=parsed.issued_at,
        nonce=parsed.nonce,
    )
