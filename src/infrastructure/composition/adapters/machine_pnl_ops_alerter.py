from __future__ import annotations

import logging

import httpx
from beartype import beartype

from src.application.machine_pnl.opex_ports import MachinePnlOpsTerminalAlerter
from src.config.settings import Settings

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class NoOpMachinePnlOpsAlerter:
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        period_id: str | None,
        event_id: str | None,
    ) -> None:
        _LOGGER.info(
            "machine_pnl ops terminal notify skipped (alert chat empty) "
            "handler_id=%s period_id=%s event_id=%s error=%s",
            handler_id,
            period_id,
            event_id,
            error_message,
        )


@beartype
class TelegramMachinePnlOpsAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        period_id: str | None,
        event_id: str | None,
    ) -> None:
        text = (
            f"machine_pnl outbox failed (terminal): handler={handler_id} "
            f"period_id={period_id} event_id={event_id} error={error_message}"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "machine_pnl ops telegram notify failed",
                exc_info=True,
                extra={
                    "handler_id": handler_id,
                    "period_id": period_id,
                    "event_id": event_id,
                    "chat_id": self._chat_id,
                },
            )
            return


@beartype
def build_machine_pnl_ops_alerter(settings: Settings) -> MachinePnlOpsTerminalAlerter:
    chat_id = settings.machine_pnl.alert_chat_id
    if chat_id is None:
        return NoOpMachinePnlOpsAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpMachinePnlOpsAlerter()
    return TelegramMachinePnlOpsAlerter(bot_token=bot_token, chat_id=chat_id)
