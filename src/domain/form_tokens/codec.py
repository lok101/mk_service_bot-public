from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class _ParsedMachineFormToken:
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str
    purpose: str | None


@beartype
@dataclass(frozen=True, slots=True)
class _ParsedTechnicianOnlyFormToken:
    technician_id: TechnicianId
    issued_at: datetime
    nonce: str
    purpose: str


@beartype
def _create_machine_form_token(
    technician_id: TechnicianId,
    machine_id: MachineId,
    issued_at: datetime,
    nonce: str,
    purpose: str,
    secret: str,
) -> str:
    if not purpose:
        raise ValueError("Machine form token purpose must not be empty")

    body = {
        "v": 1,
        "purpose": purpose,
        "technician_id": technician_id.value,
        "machine_id": machine_id.value,
        "issued_at": issued_at.astimezone(UTC).isoformat(),
        "nonce": nonce,
    }
    encoded_body = _base64_urlsafe_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    signature = _sign(encoded_body, secret)

    return f"{encoded_body}.{signature}"


@beartype
def _create_technician_only_form_token(
    technician_id: TechnicianId,
    issued_at: datetime,
    nonce: str,
    purpose: str,
    secret: str,
) -> str:
    if not purpose:
        raise ValueError("Technician-only form token purpose must not be empty")

    body = {
        "v": 1,
        "purpose": purpose,
        "technician_id": technician_id.value,
        "issued_at": issued_at.astimezone(UTC).isoformat(),
        "nonce": nonce,
    }
    encoded_body = _base64_urlsafe_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    )
    signature = _sign(encoded_body, secret)

    return f"{encoded_body}.{signature}"


@beartype
def _verify_technician_only_form_token(
    token: str,
    secret: str,
    form_name: str,
    expected_purpose: str,
    max_age_hours: float | None = None,
) -> _ParsedTechnicianOnlyFormToken:
    if not token:
        raise ValueError(f"{form_name} form token must not be empty")
    if not secret:
        raise ValueError(f"{form_name} form token secret must not be empty")

    try:
        encoded_body, signature = token.split(".", maxsplit=1)
    except ValueError as error:
        raise ValueError(f"{form_name} form token has invalid format") from error

    expected_signature = _sign(encoded_body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError(f"{form_name} form token signature is invalid")

    raw_payload = json.loads(_base64_urlsafe_decode(encoded_body).decode("utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError(f"{form_name} form token payload must be an object")

    technician_id = raw_payload.get("technician_id")
    issued_at = raw_payload.get("issued_at")
    nonce = raw_payload.get("nonce")
    purpose = raw_payload.get("purpose")
    machine_id = raw_payload.get("machine_id")

    if purpose != expected_purpose:
        raise ValueError(f"{form_name} form token purpose is invalid")
    if machine_id is not None:
        raise ValueError(f"{form_name} form token machine_id must not be present")
    if not isinstance(technician_id, str):
        raise ValueError(f"{form_name} form token technician_id is invalid")
    if not isinstance(issued_at, str):
        raise ValueError(f"{form_name} form token issued_at is invalid")
    if not isinstance(nonce, str):
        raise ValueError(f"{form_name} form token nonce is invalid")

    issued_at_utc = datetime.fromisoformat(issued_at).astimezone(UTC)
    _reject_expired_token(
        form_name=form_name,
        issued_at=issued_at_utc,
        max_age_hours=max_age_hours,
    )

    return _ParsedTechnicianOnlyFormToken(
        technician_id=TechnicianId(technician_id),
        issued_at=issued_at_utc,
        nonce=nonce,
        purpose=purpose,
    )


@beartype
def _verify_machine_form_token(
    token: str,
    secret: str,
    form_name: str,
    expected_purpose: str | None,
    allow_missing_purpose: bool,
    max_age_hours: float | None = None,
    *,
    allowed_purposes: frozenset[str] | None = None,
) -> _ParsedMachineFormToken:
    if not token:
        raise ValueError(f"{form_name} form token must not be empty")
    if not secret:
        raise ValueError(f"{form_name} form token secret must not be empty")

    try:
        encoded_body, signature = token.split(".", maxsplit=1)
    except ValueError as error:
        raise ValueError(f"{form_name} form token has invalid format") from error

    expected_signature = _sign(encoded_body, secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError(f"{form_name} form token signature is invalid")

    raw_payload = json.loads(_base64_urlsafe_decode(encoded_body).decode("utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError(f"{form_name} form token payload must be an object")

    technician_id = raw_payload.get("technician_id")
    machine_id = raw_payload.get("machine_id")
    issued_at = raw_payload.get("issued_at")
    nonce = raw_payload.get("nonce")
    purpose = raw_payload.get("purpose")
    if purpose is None and not allow_missing_purpose:
        raise ValueError(f"{form_name} form token purpose is missing")
    if purpose is not None:
        if allowed_purposes is not None:
            if purpose not in allowed_purposes:
                raise ValueError(f"{form_name} form token purpose is invalid")
        elif expected_purpose is not None and purpose != expected_purpose:
            raise ValueError(f"{form_name} form token purpose is invalid")
    if not isinstance(technician_id, str):
        raise ValueError(f"{form_name} form token technician_id is invalid")
    if not isinstance(machine_id, str):
        raise ValueError(f"{form_name} form token machine_id is invalid")
    if not isinstance(issued_at, str):
        raise ValueError(f"{form_name} form token issued_at is invalid")
    if not isinstance(nonce, str):
        raise ValueError(f"{form_name} form token nonce is invalid")

    issued_at_utc = datetime.fromisoformat(issued_at).astimezone(UTC)
    _reject_expired_token(
        form_name=form_name,
        issued_at=issued_at_utc,
        max_age_hours=max_age_hours,
    )

    parsed_purpose: str | None
    parsed_purpose = purpose if isinstance(purpose, str) else None

    return _ParsedMachineFormToken(
        technician_id=TechnicianId(technician_id),
        machine_id=MachineId(machine_id),
        issued_at=issued_at_utc,
        nonce=nonce,
        purpose=parsed_purpose,
    )


@beartype
def _reject_expired_token(
    *,
    form_name: str,
    issued_at: datetime,
    max_age_hours: float | None,
) -> None:
    if max_age_hours is None:
        return
    if max_age_hours <= 0:
        raise ValueError(f"{form_name} form token max_age_hours must be positive")

    expires_at = issued_at + timedelta(hours=max_age_hours)
    if datetime.now(tz=UTC) > expires_at:
        raise ValueError(f"{form_name} form token has expired")


@beartype
def _base64_urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@beartype
def _base64_urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@beartype
def _sign(encoded_body: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        encoded_body.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return _base64_urlsafe_encode(digest)
