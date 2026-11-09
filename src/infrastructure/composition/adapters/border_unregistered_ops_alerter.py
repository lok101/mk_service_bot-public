from __future__ import annotations

import logging

import httpx
from beartype import beartype

from src.application.outbox.border_unregistered_ops import (
    BorderUnregisteredOpsAlerter,
    DedupingBorderUnregisteredOpsAlerter,
    NoOpBorderUnregisteredOpsAlerter,
    format_border_unregistered_ops_message,
)
from src.config.settings import Settings

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class TelegramBorderUnregisteredOpsAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def notify_unregistered(
        self,
        *,
        technician_id: str,
        products: tuple[tuple[str, str], ...],
    ) -> None:
        text = format_border_unregistered_ops_message(
            technician_id=technician_id,
            products=products,
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "border_unregistered_ops telegram notify failed technician_id=%s",
                technician_id,
                exc_info=True,
            )


@beartype
def build_border_unregistered_ops_alerter(settings: Settings) -> BorderUnregisteredOpsAlerter:
    chat_id = settings.telegram.alert_chat_id
    if chat_id is None:
        return NoOpBorderUnregisteredOpsAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpBorderUnregisteredOpsAlerter()
    return DedupingBorderUnregisteredOpsAlerter(
        inner=TelegramBorderUnregisteredOpsAlerter(bot_token=bot_token, chat_id=chat_id),
    )


__all__ = [
    "TelegramBorderUnregisteredOpsAlerter",
    "build_border_unregistered_ops_alerter",
]
