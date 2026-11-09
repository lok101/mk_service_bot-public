from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime, timedelta

from beartype import beartype

from src.domain.form_tokens.codec import (
    _base64_urlsafe_decode,
    _base64_urlsafe_encode,
    _sign,
)
from src.domain.form_tokens.types import CoffeeFormPurpose, CoffeeFormTokenPayload
from src.domain.ids import MachineId, TechnicianId

_ALLOWED_PURPOSES = frozenset({"revision", "loading"})


@beartype
def create_coffee_form_token(
    payload: CoffeeFormTokenPayload,
    secret: str,
) -> str:
    if not secret:
        raise ValueError("Coffee form token secret must not be empty")
    if payload.purpose not in _ALLOWED_PURPOSES:
        raise ValueError("Coffee form token purpose is invalid")
    if not payload.product_codes:
        raise ValueError("Coffee form token product_codes must not be empty")

    body = {
        "v": 1,
        "purpose": payload.purpose,
        "technician_id": payload.technician_id.value,
        "machine_id": payload.machine_id.value,
        "product_codes": list(payload.product_codes),
        "issued_at": payload.issued_at.astimezone(UTC).isoformat(),
        "nonce": payload.nonce,
    }
    encoded_body = _base64_urlsafe_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    return f"{encoded_body}.{_sign(encoded_body, secret)}"


@beartype
def verify_coffee_form_token(
    token: str,
    secret: str,
    *,
    expected_purpose: CoffeeFormPurpose,
    max_age_hours: float | None = None,
) -> CoffeeFormTokenPayload:
    if not token:
        raise ValueError("Coffee form token must not be empty")
    if not secret:
        raise ValueError("Coffee form token secret must not be empty")
    if expected_purpose not in _ALLOWED_PURPOSES:
        raise ValueError("Coffee form expected_purpose is invalid")

    try:
        encoded_body, signature = token.split(".", maxsplit=1)
    except ValueError as error:
        raise ValueError("Coffee form token has invalid format") from error

    expected_signature = _sign(encoded_body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Coffee form token signature is invalid")

    raw_payload = json.loads(_base64_urlsafe_decode(encoded_body).decode("utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError("Coffee form token payload must be an object")

    purpose = raw_payload.get("purpose")
    if purpose != expected_purpose:
        raise ValueError("Coffee form token purpose is invalid")

    technician_id = raw_payload.get("technician_id")
    machine_id = raw_payload.get("machine_id")
    product_codes_raw = raw_payload.get("product_codes")
    issued_at = raw_payload.get("issued_at")
    nonce = raw_payload.get("nonce")

    if not isinstance(technician_id, str):
        raise ValueError("Coffee form token technician_id is invalid")
    if not isinstance(machine_id, str) or not machine_id:
        raise ValueError("Coffee form token machine_id is invalid")
    if not isinstance(issued_at, str):
        raise ValueError("Coffee form token issued_at is invalid")
    if not isinstance(nonce, str):
        raise ValueError("Coffee form token nonce is invalid")
    if not isinstance(product_codes_raw, list) or not product_codes_raw:
        raise ValueError("Coffee form token product_codes is invalid")

    product_codes = _parse_product_codes(product_codes_raw)
    issued_at_utc = datetime.fromisoformat(issued_at).astimezone(UTC)
    if max_age_hours is not None:
        if max_age_hours <= 0:
            raise ValueError("Coffee form token max_age_hours must be positive")
        expires_at = issued_at_utc + timedelta(hours=max_age_hours)
        if datetime.now(tz=UTC) > expires_at:
            raise ValueError("Coffee form token has expired")

    return CoffeeFormTokenPayload(
        purpose=expected_purpose,
        technician_id=TechnicianId(technician_id),
        machine_id=MachineId(machine_id),
        product_codes=product_codes,
        issued_at=issued_at_utc,
        nonce=nonce,
    )


@beartype
def _parse_product_codes(raw: list[object]) -> tuple[str, ...]:
    codes: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ValueError("Coffee form token product_codes is invalid")
        codes.append(item)
    return tuple(codes)
