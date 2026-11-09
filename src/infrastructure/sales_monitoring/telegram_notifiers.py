from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.sales_monitoring.status_board_errors import (
    StatusBoardMessageGoneError,
    StatusBoardNotModifiedError,
    StatusBoardTelegramError,
)

_logger = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0
# Telegram Bot API sendMessage text limit is 4096 characters.
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_PRE_OPEN = "<pre>"
_PRE_CLOSE = "</pre>"
# Keep room for <pre></pre> wrappers when sending monospace chunks.
_TELEGRAM_PRE_CONTENT_MAX = _TELEGRAM_MAX_MESSAGE_LENGTH - len(_PRE_OPEN) - len(_PRE_CLOSE)


@beartype
def split_telegram_text(
    text: str, *, max_length: int = _TELEGRAM_MAX_MESSAGE_LENGTH
) -> tuple[str, ...]:
    """Split text into Telegram-safe chunks, preferring newline boundaries."""
    if max_length < 1:
        raise ValueError("max_length must be >= 1")
    if len(text) <= max_length:
        return (text,) if text else (text,)

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        window = remaining[:max_length]
        split_at = window.rfind("\n")
        if split_at <= 0:
            split_at = max_length
        chunk = remaining[:split_at]
        if not chunk:
            chunk = remaining[:max_length]
            split_at = max_length
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    return tuple(chunks)


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
def _parse_telegram_message_id(body: str) -> int:
    try:
        message_id = json.loads(body)["result"]["message_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise StatusBoardTelegramError("Telegram send did not return message_id") from error
    if isinstance(message_id, bool) or not isinstance(message_id, int):
        raise StatusBoardTelegramError("Telegram send did not return message_id")
    return message_id


@beartype
def _post_telegram_api(*, bot_token: str, method: str, payload: Mapping[str, int | str]) -> str:
    encoded = json.dumps(dict(payload)).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/{method}",
        data=encoded,
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
            raw = response.read()
            return raw.decode("utf-8") if raw else ""
    except urllib.error.HTTPError as error:
        detail = _http_error_detail(error)
        raise urllib.error.HTTPError(
            error.url,
            error.code,
            detail,
            error.headers,
            None,
        ) from error


@beartype
def _map_status_board_http_error(error: urllib.error.HTTPError) -> StatusBoardTelegramError:
    detail = f"{error.reason or ''} {error}".strip()
    lowered = detail.lower()
    if error.code == 400:
        if "message to edit not found" in lowered or "message to be edited not found" in lowered:
            return StatusBoardMessageGoneError(detail)
        if "message is not modified" in lowered:
            return StatusBoardNotModifiedError(detail)
    return StatusBoardTelegramError(detail)


@beartype
def _post_telegram_message(*, bot_token: str, chat_id: int, text: str) -> None:
    try:
        _post_telegram_api(
            bot_token=bot_token,
            method="sendMessage",
            payload={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
        )
    except urllib.error.HTTPError as error:
        _logger.error(
            "sales_monitoring_telegram_send_failed chat_id=%s text_len=%s detail=%s",
            chat_id,
            len(text),
            error.reason or "",
        )
        raise


@beartype
@dataclass(frozen=True, slots=True)
class TelegramSalesMonitoringReportNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None

    @beartype
    def send_report(self, text: str) -> None:
        chunks = split_telegram_text(text, max_length=_TELEGRAM_PRE_CONTENT_MAX)
        for chunk in chunks:
            wrapped = wrap_telegram_pre(chunk)
            if self._send is not None:
                self._send(wrapped)
            else:
                _post_telegram_message(
                    bot_token=self.bot_token,
                    chat_id=self.chat_id,
                    text=wrapped,
                )

    @beartype
    def send_decline_report(self, text: str) -> None:
        self.send_report(text)

    @beartype
    def send_board(self, text: str) -> int:
        try:
            body = _post_telegram_api(
                bot_token=self.bot_token,
                method="sendMessage",
                payload={
                    "chat_id": self.chat_id,
                    "text": wrap_telegram_pre(text),
                    "parse_mode": "HTML",
                },
            )
        except urllib.error.HTTPError as error:
            raise _map_status_board_http_error(error) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise StatusBoardTelegramError(str(error)) from error
        return _parse_telegram_message_id(body)

    @beartype
    def edit_board(self, *, message_id: int, text: str) -> None:
        try:
            _post_telegram_api(
                bot_token=self.bot_token,
                method="editMessageText",
                payload={
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                    "text": wrap_telegram_pre(text),
                    "parse_mode": "HTML",
                },
            )
        except urllib.error.HTTPError as error:
            raise _map_status_board_http_error(error) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise StatusBoardTelegramError(str(error)) from error


@beartype
@dataclass(frozen=True, slots=True)
class TelegramSalesMonitoringAlertNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None

    @beartype
    def notify_text(self, text: str) -> None:
        try:
            if self._send is not None:
                self._send(text)
                return
            _post_telegram_message(bot_token=self.bot_token, chat_id=self.chat_id, text=text)
        except urllib.error.URLError, TimeoutError, OSError:
            _logger.error("sales_monitoring_alert_telegram_failed text=%s", text)
            raise

    @beartype
    def notify_unresolved_kit_ids(self, codes: Sequence[str]) -> None:
        if not codes:
            return
        self.notify_text("sales_monitoring unresolved kit_id: " + ", ".join(codes))
