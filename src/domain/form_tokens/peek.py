from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime

from beartype import beartype

from src.domain.form_tokens.codec import (
    _base64_urlsafe_decode,
    _sign,
    _verify_machine_form_token,
)
from src.domain.form_tokens.types import PeekedFormToken, PeekedMachineFormToken
from src.domain.ids import MachineId, TechnicianId


@beartype
def peek_form_token(token: str, secret: str) -> PeekedFormToken | None:
    """Verify signature and decode payload without TTL checks (routing correlation only)."""
    if not token or not secret:
        return None

    try:
        encoded_body, signature = token.split(".", maxsplit=1)
    except ValueError:
        return None

    expected_signature = _sign(encoded_body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        raw_payload = json.loads(_base64_urlsafe_decode(encoded_body).decode("utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError:
        return None

    if not isinstance(raw_payload, dict):
        return None

    technician_id = raw_payload.get("technician_id")
    issued_at = raw_payload.get("issued_at")
    nonce = raw_payload.get("nonce")
    purpose = raw_payload.get("purpose")
    machine_id = raw_payload.get("machine_id")

    if not isinstance(technician_id, str):
        return None
    if not isinstance(issued_at, str):
        return None
    if not isinstance(nonce, str):
        return None
    if purpose is not None and not isinstance(purpose, str):
        return None
    if machine_id is not None and not isinstance(machine_id, str):
        return None

    try:
        datetime.fromisoformat(issued_at).astimezone(UTC)
    except ValueError:
        return None

    return PeekedFormToken(
        purpose=purpose if isinstance(purpose, str) else None,
        technician_id=TechnicianId(technician_id),
        machine_id=MachineId(machine_id) if isinstance(machine_id, str) else None,
    )


@beartype
def peek_machine_form_token(token: str, secret: str) -> PeekedMachineFormToken | None:
    """Verify signature and decode payload without TTL checks (UI correlation only)."""
    if not token or not secret:
        return None

    try:
        parsed = _verify_machine_form_token(
            token=token,
            secret=secret,
            form_name="Machine",
            expected_purpose=None,
            allow_missing_purpose=True,
            max_age_hours=None,
            allowed_purposes=None,
        )
    except ValueError:
        return None

    return PeekedMachineFormToken(
        technician_id=parsed.technician_id,
        machine_id=parsed.machine_id,
        issued_at=parsed.issued_at,
        nonce=parsed.nonce,
        purpose=parsed.purpose,
    )
