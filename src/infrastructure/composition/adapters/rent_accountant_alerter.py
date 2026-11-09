from __future__ import annotations

import logging
from datetime import datetime

import httpx
from beartype import beartype

from src.application.machine_pnl.rent_ports import RentAccountantAlerter
from src.config.settings import Settings
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class NoOpRentAccountantAlerter:
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        next_retry_hours: int,
    ) -> None:
        _LOGGER.info(
            "machine_pnl rent_accountant notify skipped (chat empty) "
            "period_id=%s machine_id=%s next_retry_hours=%s",
            period_id,
            machine_id.value,
            next_retry_hours,
        )


@beartype
class TelegramRentAccountantAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        next_retry_hours: int,
    ) -> None:
        text = (
            f"machine_pnl: аренда не заполнена — заполните rent_monthly. "
            f"period_id={period_id} machine_id={machine_id.value} "
            f"opened_at={opened_at.isoformat()} closed_at={closed_at.isoformat()} "
            f"повтор через ~{next_retry_hours} ч"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "machine_pnl rent_accountant telegram notify failed",
                exc_info=True,
                extra={
                    "period_id": period_id,
                    "machine_id": machine_id.value,
                    "chat_id": self._chat_id,
                },
            )
            return


@beartype
def build_rent_accountant_alerter(settings: Settings) -> RentAccountantAlerter:
    chat_id = settings.machine_pnl.rent_accountant_chat_id
    if chat_id is None:
        return NoOpRentAccountantAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpRentAccountantAlerter()
    return TelegramRentAccountantAlerter(bot_token=bot_token, chat_id=chat_id)
