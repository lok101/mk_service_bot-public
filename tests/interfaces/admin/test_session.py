from __future__ import annotations

from src.interfaces.admin.session import pack_admin_session, unpack_admin_session


def test_unpack_admin_session_rejects_bad_signature() -> None:
    token = pack_admin_session(telegram_user_id=1, issued_at=100, secret="secret")
    bad = token[:-4] + "ffff"
    assert unpack_admin_session(bad, secret="secret", ttl_seconds=60, now_epoch=100) is None


def test_unpack_admin_session_rejects_expired() -> None:
    token = pack_admin_session(telegram_user_id=1, issued_at=100, secret="secret")
    assert unpack_admin_session(token, secret="secret", ttl_seconds=10, now_epoch=200) is None


def test_unpack_admin_session_accepts_valid() -> None:
    token = pack_admin_session(telegram_user_id=7, issued_at=100, secret="secret")
    assert unpack_admin_session(token, secret="secret", ttl_seconds=60, now_epoch=120) == 7
