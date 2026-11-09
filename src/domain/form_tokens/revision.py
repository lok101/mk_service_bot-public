from __future__ import annotations

from collections.abc import Callable

from beartype import beartype

from src.domain.form_tokens.codec import _create_machine_form_token, _verify_machine_form_token
from src.domain.form_tokens.types import RevisionFormTokenPayload


@beartype
def create_revision_form_token(
    payload: RevisionFormTokenPayload,
    secret: str,
) -> str:
    if not secret:
        raise ValueError("Revision form token secret must not be empty")

    return _create_machine_form_token(
        technician_id=payload.technician_id,
        machine_id=payload.machine_id,
        issued_at=payload.issued_at,
        nonce=payload.nonce,
        purpose="revision",
        secret=secret,
    )


@beartype
def verify_revision_form_token(
    token: str,
    secret: str,
    *,
    max_age_hours: float | None = None,
) -> RevisionFormTokenPayload:
    parsed = _verify_machine_form_token(
        token=token,
        secret=secret,
        form_name="Revision",
        expected_purpose="revision",
        allow_missing_purpose=True,
        max_age_hours=max_age_hours,
    )
    return RevisionFormTokenPayload(
        technician_id=parsed.technician_id,
        machine_id=parsed.machine_id,
        issued_at=parsed.issued_at,
        nonce=parsed.nonce,
    )


@beartype
def build_verify_revision_form_token(
    *,
    max_age_hours: float,
) -> Callable[[str, str], RevisionFormTokenPayload]:
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")

    def _verify(token: str, secret: str) -> RevisionFormTokenPayload:
        return verify_revision_form_token(
            token,
            secret,
            max_age_hours=max_age_hours,
        )

    return _verify
