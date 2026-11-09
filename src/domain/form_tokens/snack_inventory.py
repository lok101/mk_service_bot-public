from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from beartype import beartype

from src.domain.form_tokens.codec import (
    _base64_urlsafe_decode,
    _base64_urlsafe_encode,
    _sign,
)
from src.domain.form_tokens.types import SnackInventoryFormTokenPayload
from src.domain.ids import TechnicianId
from src.domain.snack_loading.events import CellKey

SnackInventoryPurpose = Literal["snack_inventory_now", "snack_inventory_as_of"]

_PURPOSE_NOW: SnackInventoryPurpose = "snack_inventory_now"
_PURPOSE_AS_OF: SnackInventoryPurpose = "snack_inventory_as_of"
_ALLOWED_PURPOSES = frozenset({_PURPOSE_NOW, _PURPOSE_AS_OF})


@beartype
def create_snack_inventory_form_token(
    payload: SnackInventoryFormTokenPayload,
    secret: str,
) -> str:
    if not secret:
        raise ValueError("Snack inventory form token secret must not be empty")
    if payload.purpose not in _ALLOWED_PURPOSES:
        raise ValueError("Snack inventory form token purpose is invalid")
    if len(payload.cell_keys) != len(payload.product_codes):
        raise ValueError("Snack inventory cell_keys and product_codes length mismatch")
    _require_cell_keys_match_machine(payload.machine_code, payload.cell_keys)

    body = {
        "v": 1,
        "purpose": payload.purpose,
        "technician_id": payload.technician_id.value,
        "machine_code": payload.machine_code,
        "fingerprint_id": payload.fingerprint_id,
        "cell_keys": [list(key) for key in payload.cell_keys],
        "product_codes": list(payload.product_codes),
        "issued_at": payload.issued_at.astimezone(UTC).isoformat(),
        "nonce": payload.nonce,
    }
    encoded_body = _base64_urlsafe_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    return f"{encoded_body}.{_sign(encoded_body, secret)}"


@beartype
def verify_snack_inventory_form_token(
    token: str,
    secret: str,
    *,
    expected_purpose: SnackInventoryPurpose,
    max_age_hours: float | None = None,
) -> SnackInventoryFormTokenPayload:
    if not token:
        raise ValueError("Snack inventory form token must not be empty")
    if not secret:
        raise ValueError("Snack inventory form token secret must not be empty")
    if expected_purpose not in _ALLOWED_PURPOSES:
        raise ValueError("Snack inventory expected_purpose is invalid")

    try:
        encoded_body, signature = token.split(".", maxsplit=1)
    except ValueError as error:
        raise ValueError("Snack inventory form token has invalid format") from error

    expected_signature = _sign(encoded_body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Snack inventory form token signature is invalid")

    raw_payload = json.loads(_base64_urlsafe_decode(encoded_body).decode("utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError("Snack inventory form token payload must be an object")

    purpose = raw_payload.get("purpose")
    if purpose != expected_purpose:
        raise ValueError("Snack inventory form token purpose is invalid")

    technician_id = raw_payload.get("technician_id")
    machine_code = raw_payload.get("machine_code")
    fingerprint_id = raw_payload.get("fingerprint_id")
    cell_keys_raw = raw_payload.get("cell_keys")
    product_codes_raw = raw_payload.get("product_codes")
    issued_at = raw_payload.get("issued_at")
    nonce = raw_payload.get("nonce")

    if not isinstance(technician_id, str):
        raise ValueError("Snack inventory form token technician_id is invalid")
    if not isinstance(machine_code, str) or not machine_code:
        raise ValueError("Snack inventory form token machine_code is invalid")
    if not isinstance(fingerprint_id, str) or not fingerprint_id:
        raise ValueError("Snack inventory form token fingerprint_id is invalid")
    if not isinstance(issued_at, str):
        raise ValueError("Snack inventory form token issued_at is invalid")
    if not isinstance(nonce, str):
        raise ValueError("Snack inventory form token nonce is invalid")
    if not isinstance(cell_keys_raw, list):
        raise ValueError("Snack inventory form token cell_keys is invalid")
    if not isinstance(product_codes_raw, list):
        raise ValueError("Snack inventory form token product_codes is invalid")

    cell_keys = _parse_cell_keys(cell_keys_raw)
    product_codes = _parse_product_codes(product_codes_raw)
    if len(cell_keys) != len(product_codes):
        raise ValueError("Snack inventory cell_keys and product_codes length mismatch")
    _require_cell_keys_match_machine(machine_code, cell_keys)

    issued_at_utc = datetime.fromisoformat(issued_at).astimezone(UTC)
    if max_age_hours is not None:
        if max_age_hours <= 0:
            raise ValueError("Snack inventory form token max_age_hours must be positive")
        expires_at = issued_at_utc + timedelta(hours=max_age_hours)
        if datetime.now(tz=UTC) > expires_at:
            raise ValueError("Snack inventory form token has expired")

    return SnackInventoryFormTokenPayload(
        purpose=expected_purpose,
        technician_id=TechnicianId(technician_id),
        machine_code=machine_code,
        fingerprint_id=fingerprint_id,
        cell_keys=cell_keys,
        product_codes=product_codes,
        issued_at=issued_at_utc,
        nonce=nonce,
    )


@beartype
def _require_cell_keys_match_machine(
    machine_code: str,
    cell_keys: tuple[CellKey, ...],
) -> None:
    for cell_key in cell_keys:
        if cell_key[0] != machine_code:
            raise ValueError(
                "Snack inventory form token cell_keys machine_code mismatch",
            )


@beartype
def _parse_cell_keys(raw: list[object]) -> tuple[CellKey, ...]:
    keys: list[CellKey] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("Snack inventory form token cell_keys is invalid")
        machine_code, logical_matrix_name, line_number = item
        if not isinstance(machine_code, str) or not isinstance(logical_matrix_name, str):
            raise ValueError("Snack inventory form token cell_keys is invalid")
        if not isinstance(line_number, int) or isinstance(line_number, bool):
            raise ValueError("Snack inventory form token cell_keys is invalid")
        keys.append((machine_code, logical_matrix_name, line_number))
    return tuple(keys)


@beartype
def _parse_product_codes(raw: list[object]) -> tuple[str, ...]:
    codes: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ValueError("Snack inventory form token product_codes is invalid")
        codes.append(item)
    return tuple(codes)
