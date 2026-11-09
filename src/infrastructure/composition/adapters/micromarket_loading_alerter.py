from __future__ import annotations

import logging

import httpx
from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.micromarket_loading.alert_sweep import MicromarketLoadingAlerter
from src.application.shared.display_names import machine_display_name
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.infrastructure.micromarket_loading.warehouse_stock_sync_worker import (
    WarehouseStockStalenessAlerter,
)

_LOGGER = logging.getLogger(__name__)
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
class NoOpMicromarketLoadingAlerter:
    def send(self, text: str) -> None:
        _LOGGER.info(
            "micromarket_loading alert skipped (alert chat empty) text=%s",
            text,
        )


@beartype
class TelegramMicromarketLoadingAlerter:
    def __init__(self, *, bot_token: str, chat_id: int) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        httpx.post(
            f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
            json={"chat_id": self._chat_id, "text": text},
            timeout=_TELEGRAM_API_TIMEOUT_SECONDS,
        ).raise_for_status()


@beartype
class LoadingAlerterWarehouseStockStalenessAdapter:
    """Maps warehouse-stock staleness onto the shared TELEGRAM_ALERT_CHAT_ID sender."""

    def __init__(self, loading_alerter: MicromarketLoadingAlerter) -> None:
        self._loading_alerter = loading_alerter

    def alert_stale_snapshot(self, *, age_seconds: float) -> None:
        self._loading_alerter.send(
            f"micromarket warehouse stock snapshot stale age_seconds={age_seconds:.0f}",
        )


@beartype
class VendingMachineNameLookup:
    def __init__(self, repository: VendingMachineRepository) -> None:
        self._repository = repository

    def display_name(self, machine_code: str) -> str:
        return machine_display_name(
            self._repository,
            MachineId(machine_code),
            missing="id",
        )


@beartype
def build_micromarket_loading_alerter(settings: Settings) -> MicromarketLoadingAlerter:
    chat_id = settings.telegram.alert_chat_id
    if chat_id is None:
        return NoOpMicromarketLoadingAlerter()
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if not bot_token:
        return NoOpMicromarketLoadingAlerter()
    return TelegramMicromarketLoadingAlerter(bot_token=bot_token, chat_id=chat_id)


@beartype
def build_micromarket_warehouse_stock_staleness_alerter(
    settings: Settings,
) -> WarehouseStockStalenessAlerter:
    return LoadingAlerterWarehouseStockStalenessAdapter(
        build_micromarket_loading_alerter(settings),
    )
