from __future__ import annotations

import json
import logging
import sys
import time
import traceback
import urllib.error
import urllib.request

from beartype import beartype

_APP_NAME = "mk_service_bot"
_MAX_MESSAGE_LENGTH = 4000
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0

AlertFingerprint = tuple[str, int, str, str]


@beartype
def build_alert_fingerprint(record: logging.LogRecord) -> AlertFingerprint:
    message_prefix = record.getMessage()[:200]
    exc_type_name = ""
    if record.exc_info is not None and record.exc_info[0] is not None:
        exc_type_name = record.exc_info[0].__name__
    return (record.name, record.levelno, message_prefix, exc_type_name)


@beartype
def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


@beartype
def format_alert_message(*, record: logging.LogRecord, environment: str) -> str:
    level_name = record.levelname
    header = f"{level_name} {_APP_NAME} [{environment}]"
    prefix_lines = [
        header,
        f"logger: {record.name}",
        record.getMessage(),
    ]
    traceback_text = ""
    if isinstance(record.exc_info, bool):
        exc_info = sys.exc_info() if record.exc_info else None
    else:
        exc_info = record.exc_info
    if exc_info and exc_info[0] is not None:
        exc_text = "".join(traceback.format_exception(*exc_info)).strip()
        if exc_text:
            traceback_text = exc_text

    if traceback_text:
        text = "\n".join([*prefix_lines, "", traceback_text])
    else:
        text = "\n".join(prefix_lines)
    if len(text) <= _MAX_MESSAGE_LENGTH:
        return text

    truncated_suffix = "\n...(truncated)"
    if not traceback_text:
        keep_length = _MAX_MESSAGE_LENGTH - len(truncated_suffix)
        return text[:keep_length] + truncated_suffix

    prefix = "\n".join([*prefix_lines, ""])
    budget = _MAX_MESSAGE_LENGTH - len(prefix) - len(truncated_suffix)
    if budget < 1:
        keep_length = _MAX_MESSAGE_LENGTH - len(truncated_suffix)
        return text[:keep_length] + truncated_suffix

    return prefix + traceback_text[-budget:] + truncated_suffix


@beartype
def send_telegram_message(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    timeout_seconds: float = _TELEGRAM_API_TIMEOUT_SECONDS,
) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status >= 400:
            raise urllib.error.HTTPError(
                request.full_url,
                response.status,
                response.reason or "",
                response.headers,
                None,
            )


class TelegramAlertHandler(logging.Handler):
    @beartype
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: int,
        environment: str,
        min_interval_seconds: float,
        redact_values: tuple[str, ...],
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._environment = environment
        self._min_interval_seconds = min_interval_seconds
        self._redact_values = redact_values
        self._last_sent_at: dict[AlertFingerprint, float] = {}

    @beartype
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not self._should_send(record):
                return
            text = format_alert_message(record=record, environment=self._environment)
            text = redact_secrets(text, self._redact_values)
            send_telegram_message(
                bot_token=self._bot_token,
                chat_id=self._chat_id,
                text=text,
            )
        except Exception:
            self.handleError(record)

    @beartype
    def _should_send(self, record: logging.LogRecord) -> bool:
        fingerprint = build_alert_fingerprint(record)
        now = time.monotonic()
        last_sent = self._last_sent_at.get(fingerprint)
        if last_sent is not None and now - last_sent < self._min_interval_seconds:
            return False
        self._last_sent_at[fingerprint] = now
        return True
