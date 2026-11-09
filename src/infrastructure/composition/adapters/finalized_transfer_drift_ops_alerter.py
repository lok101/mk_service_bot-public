from __future__ import annotations

import logging

import httpx
from beartype import beartype

from src.application.outbox.finalized_transfer_drift_ops import (
    DedupingFinalizedTransferDriftOpsAlerter,
    FinalizedTransferDriftOpsAlerter,
    NoOpFinalizedTransferDriftOpsAlerter,
    format_finalized_transfer_drift_ops_message,
)
from src.application.technician_warehouse import IgnoredFinalizedTransfer
from src.config.settings import Settings

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class TelegramFinalizedTransferDriftOpsAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def notify_drift(
        self,
        *,
        technician_id: str,
        items: tuple[IgnoredFinalizedTransfer, ...],
    ) -> None:
        text = format_finalized_transfer_drift_ops_message(
            technician_id=technician_id,
            items=items,
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "finalized_transfer_drift_ops telegram notify failed technician_id=%s",
                technician_id,
                exc_info=True,
            )


@beartype
def build_finalized_transfer_drift_ops_alerter(
    settings: Settings,
) -> FinalizedTransferDriftOpsAlerter:
    chat_id = settings.telegram.alert_chat_id
    if chat_id is None:
        return NoOpFinalizedTransferDriftOpsAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpFinalizedTransferDriftOpsAlerter()
    return DedupingFinalizedTransferDriftOpsAlerter(
        inner=TelegramFinalizedTransferDriftOpsAlerter(
            bot_token=bot_token,
            chat_id=chat_id,
        ),
    )


__all__ = [
    "TelegramFinalizedTransferDriftOpsAlerter",
    "build_finalized_transfer_drift_ops_alerter",
]
