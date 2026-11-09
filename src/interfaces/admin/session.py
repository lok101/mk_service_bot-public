from __future__ import annotations

import hashlib
import hmac

from beartype import beartype

_COOKIE_NAME = "admin_session"


@beartype
def admin_session_cookie_name() -> str:
    return _COOKIE_NAME


@beartype
def pack_admin_session(*, telegram_user_id: int, issued_at: int, secret: str) -> str:
    payload = f"{telegram_user_id}.{issued_at}"
    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


@beartype
def unpack_admin_session(
    token: str,
    *,
    secret: str,
    ttl_seconds: int,
    now_epoch: int,
) -> int | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_raw, issued_raw, provided = parts
    payload = f"{user_raw}.{issued_raw}"
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        return None
    try:
        user_id = int(user_raw)
        issued_at = int(issued_raw)
    except ValueError:
        return None
    if user_id <= 0 or ttl_seconds <= 0:
        return None
    if issued_at > now_epoch + 60:
        return None
    if now_epoch - issued_at > ttl_seconds:
        return None
    return user_id
