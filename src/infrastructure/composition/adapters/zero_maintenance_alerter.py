from __future__ import annotations

import logging
from datetime import datetime

import httpx
from beartype import beartype

from src.application.machine_pnl.opex_ports import ZeroMaintenanceAlerter
from src.config.settings import Settings
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class NoOpZeroMaintenanceAlerter:
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        maintenance_count: int,
    ) -> None:
        return None


@beartype
class TelegramZeroMaintenanceAlerter:
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
        maintenance_count: int,
    ) -> None:
        text = (
            f"machine_pnl zero_maintenance period_id={period_id} "
            f"machine_id={machine_id.value} opened_at={opened_at.isoformat()} "
            f"closed_at={closed_at.isoformat()} maintenance_count={maintenance_count}"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text},
                timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
            ).raise_for_status()
        except httpx.HTTPError:
            _LOGGER.warning(
                "machine_pnl zero_maintenance telegram notify failed",
                exc_info=True,
                extra={
                    "period_id": period_id,
                    "machine_id": machine_id.value,
                    "chat_id": self._chat_id,
                },
            )
            return


@beartype
def build_zero_maintenance_alerter(settings: Settings) -> ZeroMaintenanceAlerter:
    chat_id = settings.machine_pnl.alert_chat_id
    if chat_id is None:
        return NoOpZeroMaintenanceAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpZeroMaintenanceAlerter()
    return TelegramZeroMaintenanceAlerter(bot_token=bot_token, chat_id=chat_id)
