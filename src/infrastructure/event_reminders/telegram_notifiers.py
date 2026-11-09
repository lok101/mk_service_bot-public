from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from beartype import beartype

_logger = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_PRE_OPEN = "<pre>"
_PRE_CLOSE = "</pre>"


@beartype
def wrap_telegram_pre(text: str) -> str:
    return f"{_PRE_OPEN}{html.escape(text)}{_PRE_CLOSE}"


@beartype
def _http_error_detail(error: urllib.error.HTTPError) -> str:
    body = ""
    try:
        raw = error.read()
        body = raw.decode("utf-8", errors="replace") if raw else ""
    except Exception:
        body = ""
    reason = error.reason or ""
    if body:
        return f"HTTP Error {error.code}: {reason}: {body}"
    return f"HTTP Error {error.code}: {reason}"


@beartype
def _post_telegram_message(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    parse_mode: str | None = "HTML",
) -> None:
    body: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode is not None:
        body["parse_mode"] = parse_mode
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TELEGRAM_API_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    response.reason or "",
                    response.headers,
                    None,
                )
    except urllib.error.HTTPError as error:
        detail = _http_error_detail(error)
        _logger.error(
            "event_reminders_telegram_send_failed chat_id=%s text_len=%s detail=%s",
            chat_id,
            len(text),
            detail,
        )
        raise urllib.error.HTTPError(
            error.url,
            error.code,
            detail,
            error.headers,
            None,
        ) from error


@beartype
@dataclass(frozen=True, slots=True)
class HttpReminderNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None

    @beartype
    def send_plain_pre_content(self, text: str) -> None:
        wrapped = wrap_telegram_pre(text)
        if len(wrapped) > _TELEGRAM_MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Telegram message exceeds {_TELEGRAM_MAX_MESSAGE_LENGTH} chars after <pre> wrap"
            )
        if self._send is not None:
            self._send(wrapped)
            return
        _post_telegram_message(
            bot_token=self.bot_token,
            chat_id=self.chat_id,
            text=wrapped,
            parse_mode="HTML",
        )


@beartype
@dataclass(frozen=True, slots=True)
class HttpAlertNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None

    @beartype
    def send_text(self, text: str) -> None:
        """Send ops alert as plain sendMessage (no parse_mode — safe for sheet previews)."""
        if self._send is not None:
            self._send(text)
            return
        _post_telegram_message(
            bot_token=self.bot_token,
            chat_id=self.chat_id,
            text=text,
            parse_mode=None,
        )
