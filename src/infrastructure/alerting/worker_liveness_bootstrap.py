from __future__ import annotations

import hashlib
import logging
import tempfile
import time
from pathlib import Path

from beartype import beartype

from src.config.bootstrap_alert_env import load_bootstrap_alert_env
from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_LOGGER = logging.getLogger(__name__)
_EVENT = "worker_liveness_bootstrap_alert"


@beartype
def _marker_root() -> Path:
    return Path(tempfile.gettempdir()) / "mk_service_bot" / "worker_liveness_bootstrap"


@beartype
def _fingerprint(*, entrypoint: str, error: BaseException) -> str:
    payload = f"{entrypoint}\0{type(error).__name__}\0{error}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@beartype
def _marker_path(*, entrypoint: str, error: BaseException, root: Path) -> Path:
    safe_entrypoint = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in entrypoint)
    return root / f"{safe_entrypoint}_{_fingerprint(entrypoint=entrypoint, error=error)}.marker"


@beartype
def _cooldown_active(marker: Path, *, cooldown_seconds: int, now: float) -> bool:
    if not marker.is_file():
        return False
    try:
        sent_at = float(marker.read_text(encoding="utf-8").strip())
    except OSError, ValueError:
        return False
    return (now - sent_at) < cooldown_seconds


@beartype
def _write_marker(marker: Path, *, now: float) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{now:.6f}\n", encoding="utf-8")


@beartype
def _format_alert_text(*, entrypoint: str, error: BaseException, bot_token: str) -> str:
    text = f"bootstrap failure\nentrypoint: {entrypoint}\nerror: {type(error).__name__}: {error}"
    if bot_token:
        text = text.replace(bot_token, "***")
    return text


@beartype
def notify_bootstrap_failure(*, entrypoint: str, error: BaseException) -> None:
    """Best-effort pre-Settings ops alert. Never raises; never swallows ``error``."""
    env = load_bootstrap_alert_env()
    if not env.bot_token or env.alert_chat_id is None:
        _LOGGER.info(
            "%s skip=%s",
            _EVENT,
            "alerts_disabled",
            extra={"event": _EVENT, "skip_reason": "alerts_disabled", "entrypoint": entrypoint},
        )
        return

    cooldown_seconds = env.cooldown_seconds
    now = time.time()
    marker = _marker_path(entrypoint=entrypoint, error=error, root=_marker_root())
    if _cooldown_active(marker, cooldown_seconds=cooldown_seconds, now=now):
        _LOGGER.info(
            "%s skip=%s",
            _EVENT,
            "cooldown",
            extra={
                "event": _EVENT,
                "skip_reason": "cooldown",
                "entrypoint": entrypoint,
                "fingerprint": marker.name,
            },
        )
        return

    text = _format_alert_text(entrypoint=entrypoint, error=error, bot_token=env.bot_token)
    try:
        send_telegram_message(
            bot_token=env.bot_token,
            chat_id=env.alert_chat_id,
            text=text,
        )
    except Exception as send_exc:  # noqa: BLE001
        _LOGGER.error(
            "%s send_failed error=%s",
            _EVENT,
            send_exc,
            extra={
                "event": _EVENT,
                "entrypoint": entrypoint,
                "send_error": str(send_exc),
            },
        )
        return

    try:
        _write_marker(marker, now=now)
    except OSError as marker_exc:
        _LOGGER.error(
            "%s marker_failed error=%s",
            _EVENT,
            marker_exc,
            extra={"event": _EVENT, "entrypoint": entrypoint},
        )

    _LOGGER.info(
        "%s sent",
        _EVENT,
        extra={"event": _EVENT, "entrypoint": entrypoint, "fingerprint": marker.name},
    )


__all__ = ["notify_bootstrap_failure"]
