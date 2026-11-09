from __future__ import annotations

import logging

import httpx
from beartype import beartype

from src.application.outbox.daily_sales_demand_ops_ports import (
    DailySalesDemandOpsTerminalAlerter,
)
from src.config.settings import Settings

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class NoOpDailySalesDemandOpsAlerter:
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        sales_day: str | None,
        event_id: str | None,
    ) -> None:
        _LOGGER.info(
            "daily_sales_demand ops terminal notify skipped (alert chat empty) "
            "handler_id=%s sales_day=%s event_id=%s error=%s",
            handler_id,
            sales_day,
            event_id,
            error_message,
        )


@beartype
class TelegramDailySalesDemandOpsAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        sales_day: str | None,
        event_id: str | None,
    ) -> None:
        text = (
            f"daily_sales_demand outbox failed (terminal): handler={handler_id} "
            f"sales_day={sales_day} event_id={event_id} error={error_message}"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "daily_sales_demand ops telegram notify failed",
                exc_info=True,
                extra={
                    "handler_id": handler_id,
                    "sales_day": sales_day,
                    "event_id": event_id,
                    "chat_id": self._chat_id,
                },
            )
            return


@beartype
def build_daily_sales_demand_ops_alerter(
    settings: Settings,
) -> DailySalesDemandOpsTerminalAlerter:
    chat_id = settings.telegram.alert_chat_id
    if chat_id is None:
        return NoOpDailySalesDemandOpsAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpDailySalesDemandOpsAlerter()
    return TelegramDailySalesDemandOpsAlerter(bot_token=bot_token, chat_id=chat_id)
